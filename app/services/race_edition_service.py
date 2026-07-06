"""
race_editions 조회 (review 스키마 — CORE 전용)

CREW/REVIEW는 review DB 직접 접근 금지, 이 모듈은 CORE API 라우터에서만 사용.
"""
from datetime import date
from typing import Any


def list_upcoming_editions(limit: int = 80) -> list[dict[str, Any]]:
    """훈련 목표 선택용 — 오늘 이후(또는 일정 미정) 활성 edition.

    PostgREST 임베디드 리소스(`races!inner(...)` + dotted 필터)는 운영 Supabase에서
    "permission denied for schema review"로 실패해 두 단계 조회로 대체함
    (race_plan_service._fetch_race_info 등 기존 단일 테이블 조회 패턴과 동일하게 안전한 방식만 사용).
    """
    from app.core.database import review_db

    today = date.today().isoformat()
    cap = min(max(limit, 1), 200)

    editions = (
        review_db()
        .table("race_editions")
        .select("id, name, year, race_date, race_id")
        .eq("is_active", True)
        .order("race_date", desc=False)
        .limit(300)
        .execute()
        .data
    ) or []

    race_ids = list({e["race_id"] for e in editions if e.get("race_id") is not None})
    races_by_id: dict[int, dict[str, Any]] = {}
    if race_ids:
        races_rows = (
            review_db()
            .table("races")
            .select("id, name, is_active")
            .in_("id", race_ids)
            .eq("is_active", True)
            .execute()
            .data
        ) or []
        races_by_id = {r["id"]: r for r in races_rows}

    rows: list[dict[str, Any]] = []
    for row in editions:
        race_date = row.get("race_date")
        if race_date and str(race_date)[:10] < today:
            continue
        race = races_by_id.get(row.get("race_id"))
        if race is None:
            continue
        edition_name = (row.get("name") or "").strip()
        master_name = (race.get("name") or "").strip()
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
