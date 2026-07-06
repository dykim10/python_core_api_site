"""
race_editions 조회 (review 스키마 — CORE 전용)

CREW/REVIEW는 review DB 직접 접근 금지, 이 모듈은 CORE API 라우터에서만 사용.
"""
from datetime import date
from typing import Any


def list_upcoming_editions(limit: int = 80) -> list[dict[str, Any]]:
    """훈련 목표 선택용 — 오늘 이후(또는 일정 미정) 활성 edition."""
    from app.core.database import review_db

    today = date.today().isoformat()
    cap = min(max(limit, 1), 200)

    res = (
        review_db()
        .table("race_editions")
        .select("id, name, year, race_date, races!inner(name, is_active)")
        .eq("is_active", True)
        .eq("races.is_active", True)
        .order("race_date", desc=False)
        .limit(300)
        .execute()
    )

    rows: list[dict[str, Any]] = []
    for row in res.data or []:
        race_date = row.get("race_date")
        if race_date and str(race_date)[:10] < today:
            continue
        races = row.get("races") or {}
        edition_name = (row.get("name") or "").strip()
        master_name = (races.get("name") or "").strip()
        race_name = edition_name or master_name
        if not race_name:
            continue
        rows.append({
            "id": row["id"],
            "race_name": race_name,
            "race_date": str(race_date)[:10] if race_date else None,
            "year": row.get("year"),
        })

    rows.sort(
        key=lambda r: (
            r["race_date"] is None,
            r["race_date"] or "9999-12-31",
            -(r["year"] or 0),
            r["race_name"],
        )
    )
    return rows[:cap]
