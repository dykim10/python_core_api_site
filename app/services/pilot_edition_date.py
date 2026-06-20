"""
국내 pilot 4대회 — 연도별 race_date 조회.

catalog(config)만 사용. 미래·미확정 연도는 null → Admin 수동 입력.
"""
from __future__ import annotations

from typing import Any

PILOT_CATALOG: dict[str, dict[str, Any]] = {
    "seoul": {
        "name": "서울국제마라톤",
        "search_names": ["서울국제마라톤", "서울마라톤", "동아마라톤"],
        "dates": {"2024": "2024-03-03", "2025": "2025-03-16"},
    },
    "daegu": {
        "name": "대구마라톤",
        "search_names": ["대구마라톤"],
        "dates": {"2024": "2024-04-07", "2025": "2025-02-23"},
    },
    "gyeongju": {
        "name": "경주마라톤",
        "search_names": ["경주마라톤", "경주국제마라톤"],
        "dates": {"2024": "2024-10-20", "2025": "2025-10-18"},
    },
    "gunsan": {
        "name": "군산 새만금 국제 마라톤",
        "search_names": ["군산", "새만금"],
        "dates": {"2024": "2024-04-07", "2025": "2025-04-06"},
    },
}


def _normalize_name(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def lookup_pilot_race_date(
    key: str,
    year: int,
    *,
    fetch_external: bool = True,
) -> dict[str, Any]:
    """연도별 race_date 조회. source: catalog | null. fetch_external는 무시(하위 호환)."""
    del fetch_external
    pilot = PILOT_CATALOG.get(key)
    if not pilot:
        return {"key": key, "year": year, "race_date": None, "source": "unknown_key"}

    catalog = pilot.get("dates") or {}
    if str(year) in catalog:
        return {
            "key": key,
            "year": year,
            "name": pilot["name"],
            "race_date": catalog[str(year)],
            "source": "catalog",
        }

    return {
        "key": key,
        "year": year,
        "name": pilot["name"],
        "race_date": None,
        "source": "null",
    }


def lookup_pilot_years(
    years: list[int],
    *,
    fetch_external: bool = True,
) -> list[dict[str, Any]]:
    del fetch_external
    rows: list[dict[str, Any]] = []

    for key in PILOT_CATALOG:
        pilot = PILOT_CATALOG[key]
        catalog = pilot.get("dates") or {}

        for year in years:
            if str(year) in catalog:
                rows.append({
                    "key": key,
                    "year": year,
                    "name": pilot["name"],
                    "race_date": catalog[str(year)],
                    "source": "catalog",
                })
            else:
                rows.append({
                    "key": key,
                    "year": year,
                    "name": pilot["name"],
                    "race_date": None,
                    "source": "null",
                })

    return rows
