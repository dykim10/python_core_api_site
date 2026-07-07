"""
예약 문자 APScheduler 처리 (app/services/scheduled_sms_service.py)

CREW가 crew.scheduled_sms / scheduled_sms_recipients 에 예약을 등록하면
매 60초마다 테스트 발송(T-10분) → 본 발송(T) 순으로 처리한다.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from app.core.database import crew_db, public_db
from app.services.solapi_service import send_many
from app.utils.crypto import decrypt

logger = logging.getLogger(__name__)

TEST_PREFIX = "[테스트] "


def process_scheduled_sms() -> None:
    """APScheduler 진입점."""
    _send_test_messages()
    _send_due_messages()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_phone(raw: str | None) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    return digits if len(digits) >= 10 else None


def _phone_for_user(user_id: int) -> str | None:
    """승인된 신청서(crew.applications) phone_enc → 복호화."""
    try:
        user_res = (
            public_db()
            .table("users")
            .select("email_hash")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        users = user_res.data or []
        if not users:
            return None
        email_hash = users[0].get("email_hash")
        if not email_hash:
            return None

        app_res = (
            crew_db()
            .table("applications")
            .select("phone_enc")
            .eq("email_hash", email_hash)
            .eq("status", "approved")
            .not_.is_("phone_enc", "null")
            .order("id", desc=True)
            .limit(1)
            .execute()
        )
        apps = app_res.data or []
        if not apps:
            return None

        plain = decrypt(apps[0].get("phone_enc"))
        return _normalize_phone(plain)
    except Exception:
        logger.exception("[scheduled_sms] user_id=%s 전화번호 조회 실패", user_id)
        return None


def _phones_for_users(user_ids: list[int]) -> list[str]:
    phones: list[str] = []
    seen: set[str] = set()
    for uid in user_ids:
        phone = _phone_for_user(uid)
        if phone and phone not in seen:
            seen.add(phone)
            phones.append(phone)
    return phones


def _send_test_messages() -> None:
    threshold = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    now_iso = _utc_now_iso()

    try:
        rows = (
            crew_db()
            .table("scheduled_sms")
            .select("*")
            .eq("status", "pending")
            .is_("test_sent_at", "null")
            .lte("scheduled_at", threshold)
            .execute()
            .data
            or []
        )
    except Exception:
        logger.exception("[scheduled_sms] 테스트 대상 조회 실패")
        return

    for sms in rows:
        sms_id = sms["id"]
        try:
            test_rows = (
                crew_db()
                .table("sms_test_recipients")
                .select("user_id")
                .eq("is_active", True)
                .execute()
                .data
                or []
            )
            test_user_ids = [int(r["user_id"]) for r in test_rows if r.get("user_id")]

            if not test_user_ids:
                claimed = (
                    crew_db()
                    .table("scheduled_sms")
                    .update({"status": "test_sent", "test_sent_at": now_iso, "updated_at": now_iso})
                    .eq("id", sms_id)
                    .eq("status", "pending")
                    .execute()
                )
                if claimed.data:
                    logger.warning("[scheduled_sms] id=%s 테스트 수신자 없음 — 테스트 생략", sms_id)
                continue

            phones = _phones_for_users(test_user_ids)
            if phones:
                body = f"{TEST_PREFIX}{sms['message_body']}"
                result = send_many(phones, body, sms["sender_number"])
                if result.get("error") and not result.get("group_id"):
                    logger.error("[scheduled_sms] id=%s 테스트 발송 실패: %s", sms_id, result.get("error"))
                    continue

            claimed = (
                crew_db()
                .table("scheduled_sms")
                .update({"status": "test_sent", "test_sent_at": now_iso, "updated_at": now_iso})
                .eq("id", sms_id)
                .eq("status", "pending")
                .execute()
            )
            if claimed.data:
                logger.info("[scheduled_sms] id=%s 테스트 발송 완료 recipients=%d", sms_id, len(phones))
        except Exception:
            logger.exception("[scheduled_sms] id=%s 테스트 처리 실패", sms_id)


def _send_due_messages() -> None:
    now_iso = _utc_now_iso()

    try:
        rows = (
            crew_db()
            .table("scheduled_sms")
            .select("id")
            .in_("status", ["pending", "test_sent"])
            .lte("scheduled_at", now_iso)
            .execute()
            .data
            or []
        )
    except Exception:
        logger.exception("[scheduled_sms] 본 발송 대상 조회 실패")
        return

    for row in rows:
        sms_id = row["id"]
        try:
            claimed = (
                crew_db()
                .table("scheduled_sms")
                .update({"status": "sending", "updated_at": now_iso})
                .eq("id", sms_id)
                .in_("status", ["pending", "test_sent"])
                .execute()
            )
            if not claimed.data:
                continue

            sms = claimed.data[0]
            recipient_rows = (
                crew_db()
                .table("scheduled_sms_recipients")
                .select("user_id")
                .eq("scheduled_sms_id", sms_id)
                .eq("status", "pending")
                .execute()
                .data
                or []
            )
            user_ids = [int(r["user_id"]) for r in recipient_rows if r.get("user_id")]
            phones = _phones_for_users(user_ids)

            if not phones:
                crew_db().table("scheduled_sms").update({
                    "status": "failed",
                    "error_message": "발송 가능한 전화번호가 없습니다.",
                    "updated_at": now_iso,
                }).eq("id", sms_id).execute()
                logger.error("[scheduled_sms] id=%s 발송 가능 번호 없음 user_ids=%d", sms_id, len(user_ids))
                continue

            result = send_many(phones, sms["message_body"], sms["sender_number"])
            if result.get("error") and not result.get("group_id"):
                crew_db().table("scheduled_sms").update({
                    "status": "failed",
                    "error_message": str(result.get("error", "발송 실패"))[:1000],
                    "updated_at": now_iso,
                }).eq("id", sms_id).execute()
                logger.error("[scheduled_sms] id=%s 본 발송 실패", sms_id)
                continue

            sent_iso = _utc_now_iso()
            crew_db().table("scheduled_sms").update({
                "status": "sent",
                "sent_at": sent_iso,
                "solapi_group_id": result.get("group_id"),
                "updated_at": sent_iso,
            }).eq("id", sms_id).execute()

            crew_db().table("scheduled_sms_recipients").update({
                "status": "sent",
            }).eq("scheduled_sms_id", sms_id).eq("status", "pending").execute()

            _insert_sms_log(sms, phones, result)
            logger.info("[scheduled_sms] id=%s 본 발송 완료 recipients=%d", sms_id, len(phones))
        except Exception as e:
            logger.exception("[scheduled_sms] id=%s 본 발송 예외", sms_id)
            try:
                crew_db().table("scheduled_sms").update({
                    "status": "failed",
                    "error_message": str(e)[:1000],
                    "updated_at": _utc_now_iso(),
                }).eq("id", sms_id).execute()
            except Exception:
                logger.exception("[scheduled_sms] id=%s failed 상태 기록 실패", sms_id)


def _insert_sms_log(sms: dict, phones: list[str], result: dict) -> None:
    """기존 즉시 발송과 동일한 crew.sms_logs 이력."""
    try:
        crew_db().table("sms_logs").insert({
            "group_id": result.get("group_id"),
            "sent_by": sms.get("created_by"),
            "filter_type": "scheduled",
            "filter_value": str(sms.get("id")),
            "recipient_cnt": len(phones),
            "message": sms.get("message_body"),
            "status": "sent",
            "delivered_cnt": 0,
            "failed_cnt": 0,
            "result_data": result,
        }).execute()
    except Exception:
        # 구 스키마(sender_id/recipient_count/result) 폴백
        try:
            crew_db().table("sms_logs").insert({
                "group_id": result.get("group_id"),
                "sender_id": sms.get("created_by"),
                "target_type": "scheduled",
                "target_id": sms.get("id"),
                "recipient_count": len(phones),
                "message": sms.get("message_body"),
                "result": result,
            }).execute()
        except Exception:
            logger.exception("[scheduled_sms] sms_logs insert 실패 scheduled_sms_id=%s", sms.get("id"))
