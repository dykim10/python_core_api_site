"""
review.races 카탈로그 조회 — 최신 edition 날짜 보강.
"""
from typing import Any


def list_active_races(limit: int = 20) -> list[dict[str, Any]]:
    """is_active races + 각 race의 최신 edition race_date/year."""
    from app.core.database import review_db

    cap = min(max(int(limit), 1), 500)
    races = (
        review_db()
        .table("races")
        .select("*")
        .eq("is_active", True)
        .order("id", desc=True)
        .limit(cap)
        .execute()
        .data
    ) or []

    if not races:
        return []

    race_ids = [r["id"] for r in races if r.get("id") is not None]
    editions_by_race: dict[int, dict[str, Any]] = {}

    if race_ids:
        editions = (
            review_db()
            .table("race_editions")
            .select("race_id, year, race_date")
            .in_("race_id", race_ids)
            .eq("is_active", True)
            .execute()
            .data
        ) or []

        for ed in editions:
            rid = ed.get("race_id")
            if rid is None:
                continue
            prev = editions_by_race.get(rid)
            year = ed.get("year") or 0
            date = str(ed.get("race_date") or "")
            if prev is None:
                editions_by_race[rid] = ed
                continue
            prev_year = prev.get("year") or 0
            prev_date = str(prev.get("race_date") or "")
            # year desc, then race_date desc
            if year > prev_year or (year == prev_year and date > prev_date):
                editions_by_race[rid] = ed

    rows: list[dict[str, Any]] = []
    for race in races:
        row = dict(race)
        ed = editions_by_race.get(race.get("id"))
        if ed:
            rd = ed.get("race_date")
            row["latest_race_date"] = str(rd)[:10] if rd else None
            row["latest_edition_year"] = ed.get("year")
        else:
            row["latest_race_date"] = None
            row["latest_edition_year"] = None
        rows.append(row)

    return rows
