"""Solapi REST API 공통 (발송·인증 헤더)."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

SOLAPI_BASE_URL = "https://api.solapi.com"
MFA_AUTH_TYPE = "SMS"
MFA_TTL_SECONDS = 600

_pending_mfa: dict[str, tuple[str, float]] = {}


def _normalize_phone(phone_number: str) -> str | None:
    digits = re.sub(r"\D", "", phone_number or "")
    if len(digits) < 8 or len(digits) > 12:
        return None
    return digits


def _solapi_credentials() -> tuple[str, str] | None:
    api_key = settings.solapi_api_key
    api_secret = settings.solapi_api_secret
    if not api_key or not api_secret:
        return None
    return api_key, api_secret


def _solapi_headers(
    api_key: str,
    api_secret: str,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Authorization": solapi_auth_header(api_key, api_secret),
    }
    if extra_headers:
        headers.update(extra_headers)
    return headers


def _solapi_error_message(data: dict | list | str, fallback: str) -> str:
    if isinstance(data, dict):
        return (
            data.get("errorMessage")
            or data.get("message")
            or fallback
        )
    return fallback


def _solapi_request(
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout: int = 15,
) -> tuple[int, dict | list | str]:
    creds = _solapi_credentials()
    if creds is None:
        return 503, {"errorMessage": "Solapi 인증 정보가 설정되지 않았습니다."}

    api_key, api_secret = creds
    try:
        resp = requests.request(
            method,
            f"{SOLAPI_BASE_URL}{path}",
            json=json_body,
            headers=_solapi_headers(api_key, api_secret, extra_headers),
            timeout=timeout,
        )
        try:
            data = resp.json()
        except ValueError:
            data = resp.text
        return resp.status_code, data
    except Exception as exc:
        logger.exception("[SMS] solapi 요청 실패 path=%s", path)
        return 500, {"errorMessage": str(exc)}


def _store_pending_mfa(phone_number: str, transaction_id: str) -> None:
    _pending_mfa[phone_number] = (transaction_id, time.time())


def _take_pending_mfa(phone_number: str) -> str | None:
    entry = _pending_mfa.get(phone_number)
    if not entry:
        return None
    transaction_id, created_at = entry
    if time.time() - created_at > MFA_TTL_SECONDS:
        _pending_mfa.pop(phone_number, None)
        return None
    return transaction_id


def _clear_pending_mfa(phone_number: str) -> None:
    _pending_mfa.pop(phone_number, None)


def _sender_status(data: dict | list | str, phone_number: str) -> str | None:
    if not isinstance(data, dict):
        return None
    for item in data.get("senderIds", []):
        if item.get("phoneNumber") == phone_number:
            return item.get("status")
    return None


def list_sender_numbers(*, include_all_statuses: bool = False) -> dict:
    """Solapi 발신번호 목록 조회."""
    status_code, data = _solapi_request("GET", "/senderid/v1/numbers")
    if status_code != 200 or not isinstance(data, dict):
        return {
            "senders": [],
            "error": _solapi_error_message(data, "발신번호 목록 조회에 실패했습니다."),
        }

    items = [
        {
            "phoneNumber": item.get("phoneNumber"),
            "status": item.get("status"),
        }
        for item in data.get("senderIds", [])
        if item.get("phoneNumber")
    ]

    if include_all_statuses:
        return {"senders": items}

    return {
        "senders": [
            item["phoneNumber"]
            for item in items
            if item.get("status") == "ACTIVE"
        ]
    }


def register_sender(phone_number: str) -> dict:
    """개인 휴대폰 번호를 SELF-CERT(SMS)로 등록하고 인증코드를 요청한다."""
    phone = _normalize_phone(phone_number)
    if phone is None:
        return {"error": "유효하지 않은 전화번호입니다. (8~12자리 숫자)"}

    create_status, create_data = _solapi_request(
        "POST",
        "/senderid/v1/numbers",
        json_body={"phoneNumber": phone},
    )
    if create_status not in (200, 201) and create_status != 409:
        if isinstance(create_data, dict) and _sender_status(create_data, phone):
            pass
        elif create_status != 400:
            return {
                "error": _solapi_error_message(
                    create_data,
                    "발신번호 등록에 실패했습니다.",
                )
            }

    mfa_payload = {
        "authType": MFA_AUTH_TYPE,
        "extras": {"phoneNumber": phone},
    }
    auth_status, auth_data = _solapi_request(
        "PUT",
        f"/senderid/v1/numbers/{phone}/authenticate",
        extra_headers={"x-mfa-data": json.dumps(mfa_payload, ensure_ascii=False)},
    )
    if auth_status not in (200, 201):
        return {
            "error": _solapi_error_message(
                auth_data,
                "인증코드 요청에 실패했습니다.",
            )
        }

    transaction_id = None
    if isinstance(auth_data, dict):
        mfa = auth_data.get("mfa") or {}
        transaction_id = mfa.get("transactionId")

    if not transaction_id:
        return {"error": "인증 세션을 시작하지 못했습니다. 잠시 후 다시 시도해주세요."}

    _store_pending_mfa(phone, transaction_id)
    return {"ok": True, "phone_number": phone}


def verify_sender(phone_number: str, certification_code: str) -> dict:
    """인증코드 제출 후 ACTIVE 전환."""
    phone = _normalize_phone(phone_number)
    if phone is None:
        return {"error": "유효하지 않은 전화번호입니다. (8~12자리 숫자)"}

    code = (certification_code or "").strip()
    if not code:
        return {"error": "인증코드를 입력해주세요."}

    transaction_id = _take_pending_mfa(phone)
    if not transaction_id:
        return {"error": "인증코드 요청을 먼저 진행해주세요. (10분 이내)"}

    mfa_payload = {
        "authType": MFA_AUTH_TYPE,
        "extras": {"phoneNumber": phone},
        "transactionId": transaction_id,
        "token": code,
    }
    auth_status, auth_data = _solapi_request(
        "PUT",
        f"/senderid/v1/numbers/{phone}/authenticate",
        extra_headers={"x-mfa-data": json.dumps(mfa_payload, ensure_ascii=False)},
    )
    if auth_status not in (200, 201):
        return {
            "error": _solapi_error_message(
                auth_data,
                "인증코드 확인에 실패했습니다.",
            )
        }

    status = _sender_status(auth_data, phone)
    if status != "ACTIVE":
        return {"error": "인증에 실패했습니다. 인증코드를 확인해주세요."}

    _clear_pending_mfa(phone)
    return {"ok": True, "phone_number": phone, "status": status}


def delete_sender(phone_number: str) -> dict:
    """등록된 발신번호 삭제 (ACTIVE는 INACTIVE 후 삭제)."""
    phone = _normalize_phone(phone_number)
    if phone is None:
        return {"error": "유효하지 않은 전화번호입니다. (8~12자리 숫자)"}

    list_status, list_data = _solapi_request("GET", "/senderid/v1/numbers")
    if list_status != 200:
        return {
            "error": _solapi_error_message(
                list_data,
                "발신번호 상태 조회에 실패했습니다.",
            )
        }

    status = _sender_status(list_data, phone)
    if status is None:
        return {"error": "등록되지 않은 발신번호입니다."}

    if status == "ACTIVE":
        inactive_status, inactive_data = _solapi_request(
            "PUT",
            f"/senderid/v1/numbers/{phone}",
            json_body={"status": "INACTIVE"},
        )
        if inactive_status not in (200, 201):
            return {
                "error": _solapi_error_message(
                    inactive_data,
                    "발신번호 비활성화에 실패했습니다.",
                )
            }

    delete_status, delete_data = _solapi_request(
        "DELETE",
        f"/senderid/v1/numbers/{phone}",
    )
    if delete_status not in (200, 204):
        return {
            "error": _solapi_error_message(
                delete_data,
                "발신번호 삭제에 실패했습니다.",
            )
        }

    _clear_pending_mfa(phone)
    return {"ok": True, "phone_number": phone}


def solapi_auth_header(api_key: str, api_secret: str) -> str:
    date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    salt = uuid.uuid4().hex
    signature = hmac.new(
        api_secret.encode("utf-8"),
        (date + salt).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"HMAC-SHA256 apiKey={api_key}, date={date}, salt={salt}, signature={signature}"


def send_many(phones: list[str], message: str, sender: str) -> dict:
    """솔라피 일괄 발송. 전화번호 평문은 로그에 남기지 않는다."""
    api_key = settings.solapi_api_key
    api_secret = settings.solapi_api_secret

    if not api_key or not api_secret:
        return {
            "success_count": 0,
            "fail_count": len(phones),
            "error": "Solapi 인증 정보가 설정되지 않았습니다.",
        }

    if not sender:
        return {
            "success_count": 0,
            "fail_count": len(phones),
            "error": "발신 번호가 설정되지 않았습니다.",
        }

    if not phones:
        return {
            "success_count": 0,
            "fail_count": 0,
            "error": "발송 대상 전화번호가 없습니다.",
        }

    messages = [{"to": phone, "from": sender, "text": message} for phone in phones]

    try:
        resp = requests.post(
            "https://api.solapi.com/messages/v4/send-many",
            json={"messages": messages},
            headers={
                "Content-Type": "application/json",
                "Authorization": solapi_auth_header(api_key, api_secret),
            },
            timeout=60,
        )
        data = resp.json()

        if resp.status_code == 200:
            count = data.get("count", {})
            logger.info(
                "[SMS] solapi 발송 완료 recipients=%d success=%s fail=%s",
                len(phones),
                count.get("sentSuccess", 0),
                count.get("sentFailed", 0),
            )
            return {
                "success_count": count.get("sentSuccess", 0),
                "fail_count": count.get("sentFailed", 0),
                "group_id": data.get("groupId"),
                "raw": data,
            }

        logger.error("[SMS] solapi HTTP %s", resp.status_code)
        return {
            "success_count": 0,
            "fail_count": len(phones),
            "error": data.get("errorMessage", resp.text),
            "raw": data,
        }
    except Exception as e:
        logger.exception("[SMS] solapi 요청 실패")
        return {
            "success_count": 0,
            "fail_count": len(phones),
            "error": str(e),
        }
