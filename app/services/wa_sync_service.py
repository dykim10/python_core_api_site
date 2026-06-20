"""
World Athletics Label Road Races → review.races 마스터 카탈로그 sync.

정합성 원칙 (2026-06-20 확정):
  - 소스: World Athletics 공식 GraphQL (Wikipedia 폐기)
  - races 마스터만 — race_editions 미생성 (TASK-REMODEL-02)
  - wa_calendar[season]: 연도별 Label Road Races 등재 이력
  - season sync 1회 = 해당 시즌 공인 목록 기준 upsert + 미등재 대회 delist

공인 판정 (시즌 Y sync 후):
  - Y 목록에 있음     → wa_calendar[Y].listed=true,  is_certified=true,  wa_label 설정
  - Y 목록에 없음     → wa_calendar[Y].listed=false, is_certified=false, wa_label=null
    (과거 wa_calendar[Y-1].listed=true 는 이력으로 유지 → UI "24 공인 / 25 비공인")
  - Y에만 신규        → insert (신규 공인 대회)
  - 국내 is_domestic=true 카탈로그는 sync 대상 제외
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.core.database import review_db
from app.services.race_crawler import crawl_wa_label_races, translate_race_names_to_korean

logger = logging.getLogger(__name__)

_ISO3_COUNTRY: dict[str, str] = {
    "KOR": "대한민국",
    "JPN": "일본",
    "USA": "미국",
    "GBR": "영국",
    "CHN": "중국",
    "AUS": "호주",
    "DEU": "독일",
    "FRA": "프랑스",
    "ESP": "스페인",
    "ITA": "이탈리아",
    "NLD": "네덜란드",
    "BEL": "벨기에",
    "CHE": "스위스",
    "AUT": "오스트리아",
    "POL": "폴란드",
    "CZE": "체코",
    "HUN": "헝가리",
    "SWE": "스웨덴",
    "NOR": "노르웨이",
    "DNK": "덴마크",
    "FIN": "핀란드",
    "PRT": "포르투갈",
    "IRL": "아일랜드",
    "CAN": "캐나다",
    "MEX": "멕시코",
    "BRA": "브라질",
    "ARG": "아르헨티나",
    "IND": "인도",
    "SGP": "싱가포르",
    "HKG": "홍콩",
    "TWN": "대만",
    "THA": "태국",
    "MYS": "말레이시아",
    "IDN": "인도네시아",
    "PHL": "필리핀",
    "VNM": "베트남",
    "NZL": "뉴질랜드",
    "ZAF": "남아프리카",
    "KEN": "케냐",
    "ETH": "에티오피아",
    "QAT": "카타르",
    "ARE": "아랍에미리트",
    "SAU": "사우디아라비아",
    "TUR": "튀르키예",
    "RUS": "러시아",
    "UKR": "우크라이나",
    "GER": "독일",
}


def country_name(iso3: str) -> str:
    code = (iso3 or "").strip().upper()
    return _ISO3_COUNTRY.get(code, code)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _calendar_entry_listed(race: dict, sync_year: int) -> dict[str, Any]:
    """시즌 Label Road Races 등재 — listed=true."""
    return {
        "listed": True,
        "start_date": race.get("race_date"),
        "end_date": race.get("end_date"),
        "wa_competition_id": race.get("wa_competition_id"),
        "source_url": race.get("source_url"),
        "wa_label": race.get("wa_label"),
        "venue": race.get("venue") or race.get("location"),
        "synced_at": _now_iso(),
        "sync_season": sync_year,
    }


def _calendar_entry_delisted(sync_year: int) -> dict[str, Any]:
    """해당 시즌 Label Road Races 목록 미등재 — listed=false."""
    return {
        "listed": False,
        "synced_at": _now_iso(),
        "sync_season": sync_year,
    }


def _merge_wa_calendar(existing: Any, sync_year: int, entry: dict[str, Any]) -> dict[str, Any]:
    cal: dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    cal[str(sync_year)] = entry
    return cal


def _race_name_key(row: dict) -> str:
    return (row.get("name_en") or row.get("name") or "").strip().lower()


def _is_wa_certification_target(row: dict) -> bool:
    """국내 카탈로그 제외 — WA 공인 갱신 대상만."""
    if row.get("is_domestic"):
        return False
    cal = row.get("wa_calendar") or {}
    if isinstance(cal, dict) and cal:
        return True
    return bool(row.get("is_certified"))


def sync_wa_label_races(
    year: int,
    *,
    translate: bool = True,
    fetch_organiser: bool = True,
    live: bool = False,
) -> dict[str, Any]:
    """WA 시즌 Y Label Road Races → races upsert + 연도별 공인/비공인 갱신."""
    wa_races = crawl_wa_label_races(year, fetch_organiser=fetch_organiser)
    if not wa_races:
        return {
            "year": year,
            "total": 0,
            "inserted": 0,
            "updated": 0,
            "decertified": 0,
            "skipped": 0,
        }

    if translate:
        wa_races = translate_race_names_to_korean(wa_races)

    db = review_db(live)

    races_res = db.table("races").select(
        "id,name,name_en,wa_label,is_certified,is_domestic,wa_calendar"
    ).execute()
    all_rows = races_res.data or []

    races_by_name_en: dict[str, dict] = {}
    for row in all_rows:
        key = _race_name_key(row)
        if key:
            races_by_name_en[key] = row

    inserted = updated = decertified = skipped = 0
    synced_keys: set[str] = set()

    for race in wa_races:
        name_en = (race.get("name_en") or race.get("name") or "").strip()
        key = name_en.lower()
        if not key:
            skipped += 1
            continue

        synced_keys.add(key)
        existing_race = races_by_name_en.get(key)
        cal_entry = _calendar_entry_listed(race, year)

        race_payload: dict[str, Any] = {
            "name": race.get("name") or name_en,
            "name_en": name_en,
            "city": race.get("city") or "",
            "country": country_name(race.get("country", "")),
            "wa_label": race.get("wa_label"),
            "is_certified": True,
            "is_domestic": False,
            "is_active": True,
            "wa_calendar": _merge_wa_calendar(
                existing_race.get("wa_calendar") if existing_race else {},
                year,
                cal_entry,
            ),
        }
        if race.get("official_url"):
            race_payload["official_url"] = race["official_url"]
        if race.get("website_url"):
            race_payload["website_url"] = race["website_url"]
        if race.get("organizer"):
            race_payload["organizer"] = race["organizer"]

        if existing_race:
            db.table("races").update(race_payload).eq("id", existing_race["id"]).execute()
            existing_race.update(race_payload)
            updated += 1
        else:
            ins = db.table("races").insert(race_payload).execute()
            if ins.data:
                row = ins.data[0]
                races_by_name_en[key] = row
                all_rows.append(row)
                inserted += 1
            else:
                skipped += 1

    # 시즌 Y 목록에 없는 WA 추적 대회 → 해당 시즌 비공인 처리
    for row in all_rows:
        if not _is_wa_certification_target(row):
            continue
        key = _race_name_key(row)
        if not key or key in synced_keys:
            continue

        new_cal = _merge_wa_calendar(
            row.get("wa_calendar"),
            year,
            _calendar_entry_delisted(year),
        )
        db.table("races").update({
            "wa_calendar": new_cal,
            "is_certified": False,
            "wa_label": None,
        }).eq("id", row["id"]).execute()
        decertified += 1

    logger.info(
        "WA sync season=%s: inserted=%d updated=%d decertified=%d skipped=%d",
        year,
        inserted,
        updated,
        decertified,
        skipped,
    )

    return {
        "year": year,
        "total": len(wa_races),
        "inserted": inserted,
        "updated": updated,
        "decertified": decertified,
        "skipped": skipped,
    }
