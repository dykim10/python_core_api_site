"""system_logs 테이블 적재 (CORE). 어떤 경우에도 예외를 밖으로 던지지 않는다."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("system_log")

VALID_LEVELS = {"info", "warning", "error"}

RETENTION_DAYS = 30


def _json_safe(context: dict) -> dict:
    try:
        return json.loads(json.dumps(context, default=str, ensure_ascii=False))
    except Exception:
        return {"_context_error": "직렬화 실패"}


def db_log(category: str, level: str, message: str, context: dict | None = None) -> None:
    try:
        from app.core.database import public_db

        safe_message = str(message).replace("\x00", "")[:2000]

        # live=True 아님 주의: 운영 Parameter Store에 SUPABASE_LIVE_URL/KEY가 없어
        # live=True는 매번 ValueError로 실패한다 (04-api-endpoints.md review_db와 동일 원인).
        # 현재 운영은 default 연결(SUPABASE_URL)이 GRANT 적용된 실 DB.
        public_db().table("system_logs").insert({
            "source": "core",
            "category": category,
            "level": level if level in VALID_LEVELS else "info",
            "message": safe_message,
            "context": _json_safe(context or {}),
        }).execute()
    except Exception as e:
        try:
            logger.error("system_logs insert 실패: %s / 원본: %s", e, str(message)[:500])
        except Exception:
            pass


def cleanup_old_logs() -> None:
    """30일 초과 system_logs 삭제."""
    try:
        from app.core.database import public_db

        cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
        public_db().table("system_logs").delete().lt("created_at", cutoff).execute()
        db_log("scheduler", "info", "system_logs 30일 초과분 정리 완료")
    except Exception as e:
        try:
            logger.error("system_logs cleanup 실패: %s", e)
        except Exception:
            pass
