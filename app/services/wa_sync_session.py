"""
WA Label sync 세션 — 중지 요청·변경 추적·롤백.

세션 파일: /tmp/wa_sync_sessions/{session_id}.json (core-api 프로세스 간 공유)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SESSION_DIR = Path("/tmp/wa_sync_sessions")

ROLLBACK_COLUMNS = (
    "name",
    "name_en",
    "city",
    "country",
    "wa_label",
    "is_certified",
    "is_domestic",
    "is_active",
    "wa_calendar",
    "official_url",
    "website_url",
    "organizer",
)


class WaSyncCancelled(Exception):
    """사용자 중지 — 롤백 후 반환."""

    def __init__(self, session_id: str, rollback: dict[str, Any]):
        self.session_id = session_id
        self.rollback = rollback
        super().__init__(f"WA sync cancelled: {session_id}")


def _path(session_id: str) -> Path:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    return SESSION_DIR / f"{safe}.json"


def _load(session_id: str) -> dict[str, Any] | None:
    path = _path(session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("WA session load failed %s: %s", session_id, e)
        return None


def _save(session_id: str, data: dict[str, Any]) -> None:
    path = _path(session_id)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def request_cancel(session_id: str) -> dict[str, Any]:
    """중지 요청 (sync 시작 전에도 호출 가능)."""
    data = _load(session_id) or {
        "session_id": session_id,
        "year": None,
        "status": "pending",
        "inserted_ids": [],
        "updated_snapshots": {},
        "decertified_snapshots": {},
    }
    data["cancel_requested"] = True
    data["status"] = "cancelling"
    _save(session_id, data)
    return data


def open_session(session_id: str, year: int) -> "WaSyncSession":
    existing = _load(session_id)
    if existing and existing.get("cancel_requested"):
        sess = WaSyncSession(session_id, year, existing)
        raise WaSyncCancelled(session_id, sess.rollback())
    data = {
        "session_id": session_id,
        "year": year,
        "status": "running",
        "cancel_requested": False,
        "inserted_ids": [],
        "updated_snapshots": {},
        "decertified_snapshots": {},
    }
    _save(session_id, data)
    return WaSyncSession(session_id, year, data)


class WaSyncSession:
    def __init__(self, session_id: str, year: int, data: dict[str, Any]):
        self.session_id = session_id
        self.year = year
        self._data = data

    def _persist(self) -> None:
        _save(self.session_id, self._data)

    def check_cancel(self) -> None:
        fresh = _load(self.session_id)
        if fresh:
            self._data = fresh
        if self._data.get("cancel_requested"):
            result = self.rollback()
            raise WaSyncCancelled(self.session_id, result)

    def snapshot_row(self, row: dict[str, Any]) -> dict[str, Any]:
        snap: dict[str, Any] = {}
        for col in ROLLBACK_COLUMNS:
            if col in row:
                snap[col] = row[col]
        return snap

    def record_update_before(self, race_id: int, row: dict[str, Any]) -> None:
        key = str(race_id)
        if key not in self._data["updated_snapshots"]:
            self._data["updated_snapshots"][key] = self.snapshot_row(row)
            self._persist()

    def record_decertify_before(self, race_id: int, row: dict[str, Any]) -> None:
        key = str(race_id)
        if key not in self._data["decertified_snapshots"]:
            self._data["decertified_snapshots"][key] = self.snapshot_row(row)
            self._persist()

    def record_inserts(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            rid = row.get("id")
            if rid is not None:
                self._data["inserted_ids"].append(int(rid))
        self._persist()

    def rollback(self, db=None) -> dict[str, Any]:
        """이번 세션에서 변경한 rows 되돌림."""
        from app.core.database import review_db

        db = db or review_db()
        deleted = restored_updates = restored_decert = 0
        errors: list[str] = []

        for rid in reversed(self._data.get("inserted_ids") or []):
            try:
                db.table("races").delete().eq("id", rid).execute()
                deleted += 1
            except Exception as e:
                errors.append(f"delete id={rid}: {e}")

        for rid, snap in (self._data.get("updated_snapshots") or {}).items():
            try:
                db.table("races").update(snap).eq("id", int(rid)).execute()
                restored_updates += 1
            except Exception as e:
                errors.append(f"restore update id={rid}: {e}")

        for rid, snap in (self._data.get("decertified_snapshots") or {}).items():
            try:
                db.table("races").update(snap).eq("id", int(rid)).execute()
                restored_decert += 1
            except Exception as e:
                errors.append(f"restore decert id={rid}: {e}")

        self._data["status"] = "cancelled"
        self._persist()

        result = {
            "deleted_inserts": deleted,
            "restored_updates": restored_updates,
            "restored_decertified": restored_decert,
            "errors": errors,
        }
        logger.info("WA sync rollback session=%s: %s", self.session_id, result)
        return result

    def mark_done(self) -> None:
        self._data["status"] = "done"
        self._persist()
        try:
            _path(self.session_id).unlink(missing_ok=True)
        except OSError:
            pass
