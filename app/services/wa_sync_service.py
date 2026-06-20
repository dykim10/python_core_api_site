"""
World Athletics Label Road Races → review.races + review.race_editions sync.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any, Optional

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


def edition_status(race_date: Optional[str]) -> str:
    if not race_date:
        return "upcoming"
    try:
        return "ended" if date.fromisoformat(race_date) < date.today() else "upcoming"
    except ValueError:
        return "upcoming"


def sync_wa_label_races(
    year: int,
    *,
    translate: bool = True,
    fetch_organiser: bool = True,
    live: bool = False,
) -> dict[str, Any]:
    """WA 라벨 대회를 races + race_editions에 upsert."""
    wa_races = crawl_wa_label_races(year, fetch_organiser=fetch_organiser)
    if not wa_races:
        return {
            "year": year,
            "total": 0,
            "races_inserted": 0,
            "races_updated": 0,
            "editions_inserted": 0,
            "editions_updated": 0,
            "skipped": 0,
        }

    if translate:
        wa_races = translate_race_names_to_korean(wa_races)

    db = review_db(live)

    races_res = db.table("races").select("id,name,name_en,wa_label").execute()
    races_by_name_en: dict[str, dict] = {}
    for row in races_res.data or []:
        for key in (row.get("name_en"), row.get("name")):
            if key:
                races_by_name_en[key.lower()] = row

    editions_res = db.table("race_editions").select(
        "id,race_id,year,wa_competition_id"
    ).execute()
    editions_by_wa_id = {
        row["wa_competition_id"]: row
        for row in (editions_res.data or [])
        if row.get("wa_competition_id")
    }
    editions_by_race_year = {
        (row["race_id"], row["year"]): row
        for row in (editions_res.data or [])
        if row.get("race_id") is not None
    }

    races_inserted = races_updated = 0
    editions_inserted = editions_updated = 0
    skipped = 0

    for race in wa_races:
        name_en = (race.get("name_en") or race.get("name") or "").strip()
        if not name_en:
            skipped += 1
            continue

        wa_comp_id = race.get("wa_competition_id")
        existing_race = races_by_name_en.get(name_en.lower())
        race_id: Optional[int] = existing_race["id"] if existing_race else None

        race_payload = {
            "name": race.get("name") or name_en,
            "name_en": name_en,
            "city": race.get("city") or "",
            "country": country_name(race.get("country", "")),
            "wa_label": race.get("wa_label"),
            "is_certified": True,
            "is_domestic": False,
            "is_active": True,
        }
        if race.get("official_url"):
            race_payload["official_url"] = race["official_url"]
        if race.get("website_url"):
            race_payload["website_url"] = race["website_url"]
        if race.get("organizer"):
            race_payload["organizer"] = race["organizer"]

        if race_id:
            db.table("races").update(race_payload).eq("id", race_id).execute()
            races_updated += 1
        else:
            ins = db.table("races").insert(race_payload).execute()
            if ins.data:
                race_id = ins.data[0]["id"]
                races_by_name_en[name_en.lower()] = {"id": race_id, **race_payload}
                races_inserted += 1
            else:
                skipped += 1
                continue

        year_val = int(race.get("year") or year)
        race_date = race.get("race_date")
        edition_payload = {
            "race_id": race_id,
            "name": name_en,
            "year": year_val,
            "race_date": race_date,
            "location": race.get("location") or race.get("venue") or "",
            "city": race.get("city") or "",
            "country": country_name(race.get("country", "")),
            "is_domestic": False,
            "source": "world_athletics",
            "source_url": race.get("source_url", ""),
            "status": edition_status(race_date),
            "is_review_open": False,
            "is_active": True,
        }
        if wa_comp_id is not None:
            edition_payload["wa_competition_id"] = wa_comp_id

        existing_ed = None
        if wa_comp_id:
            existing_ed = editions_by_wa_id.get(wa_comp_id)
        if not existing_ed and race_id:
            existing_ed = editions_by_race_year.get((race_id, year_val))

        if existing_ed:
            db.table("race_editions").update(edition_payload).eq(
                "id", existing_ed["id"]
            ).execute()
            editions_updated += 1
        else:
            ins_ed = db.table("race_editions").insert(edition_payload).execute()
            if ins_ed.data:
                editions_inserted += 1
                new_id = ins_ed.data[0]["id"]
                if wa_comp_id:
                    editions_by_wa_id[wa_comp_id] = {"id": new_id, "race_id": race_id, "year": year_val}
                editions_by_race_year[(race_id, year_val)] = {"id": new_id, "race_id": race_id, "year": year_val}
            else:
                skipped += 1

    return {
        "year": year,
        "total": len(wa_races),
        "races_inserted": races_inserted,
        "races_updated": races_updated,
        "editions_inserted": editions_inserted,
        "editions_updated": editions_updated,
        "skipped": skipped,
    }
