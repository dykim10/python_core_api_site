"""
국내 pilot 4대회 — 연도별 race_date 조회.

우선순위: catalog → marathongo slug → marathongo 검색(q) → marathongo 목록 → null.
marathongo 표기 예: '2026 서울마라톤' / slug: 2026-seoul-international-marathon.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

PILOT_CATALOG: dict[str, dict[str, Any]] = {
    "seoul": {
        "name": "서울국제마라톤",
        "search_query": "서울마라톤",
        "search_names": ["서울마라톤", "서울국제마라톤", "동아마라톤"],
        "title_aliases": ["서울마라톤"],
        "slug_templates": [
            "{year}-seoul-international-marathon",
            "{year}-seoul-marathon",
        ],
        "slug_keyword": "seoul-marathon",
        "exclude_names": ["MBN", "YTN", "오픈", "한강", "하프", "10km", "10K", "레이스", "서울런"],
        "dates": {"2024": "2024-03-03", "2025": "2025-03-16"},
    },
    "daegu": {
        "name": "대구마라톤",
        "search_query": "대구마라톤",
        "search_names": ["대구마라톤", "대구국제마라톤"],
        "title_aliases": ["대구마라톤"],
        "slug_templates": ["{year}-daegu-marathon"],
        "slug_overrides": {"2026": "2026-daegu-marathon-feb22"},
        "slug_keyword": "daegu-marathon",
        "exclude_names": ["10km", "10K", "세계마스터즈", "하프", "북구", "달서"],
        "dates": {"2024": "2024-04-07", "2025": "2025-02-23"},
    },
    "gyeongju": {
        "name": "경주마라톤",
        "search_query": "경주마라톤",
        "search_names": ["경주마라톤", "경주국제마라톤"],
        "title_aliases": ["경주마라톤"],
        "slug_templates": ["{year}-gyeongju-marathon"],
        "slug_keyword": "gyeongju-marathon",
        "exclude_names": [],
        "dates": {"2024": "2024-10-20", "2025": "2025-10-18"},
    },
    "gunsan": {
        "name": "군산 새만금 국제 마라톤",
        "search_query": "군산 새만금",
        "search_names": ["군산새만금", "군산 새만금", "군산새만금마라톤"],
        "title_aliases": ["군산 새만금", "군산새만금", "군산 새만금마라톤"],
        "slug_templates": ["{year}-gunsan-saemangeum-marathon"],
        "slug_keyword": "gunsan-saemangeum",
        "exclude_names": ["김제", "지평선", "천사데이", "동두천"],
        "dates": {"2024": "2024-04-07", "2025": "2025-04-06"},
    },
}


def _normalize_name(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def _is_excluded(candidate: str, exclude_names: list[str]) -> bool:
    raw = candidate or ""
    norm = _normalize_name(raw)
    for ex in exclude_names:
        ex_norm = _normalize_name(ex)
        if ex_norm and ex_norm in norm:
            return True
        if ex and ex in raw:
            return True
    return False


def _marathongo_title_matches(name: str, year: int, title_aliases: list[str]) -> bool:
    """marathongo 관용 표기: '2026 서울마라톤', '2026 군산 새만금마라톤'."""
    raw = (name or "").strip()
    if not raw:
        return False
    raw_norm = _normalize_name(raw)
    for alias in title_aliases:
        alias = alias.strip()
        if not alias:
            continue
        if re.match(rf"^{year}\s*{re.escape(alias)}\s*$", raw):
            return True
        alias_norm = _normalize_name(alias)
        if raw_norm == _normalize_name(f"{year}{alias}"):
            return True
        if raw_norm == _normalize_name(f"{year} {alias}"):
            return True
        # '2026 군산 새만금마라톤' — alias '군산 새만금' 포함
        if raw_norm.startswith(str(year)) and alias_norm in raw_norm:
            return True
    return False


def _match_score(candidate: str, search_names: list[str], pilot_name: str) -> int:
    cand = _normalize_name(candidate)
    if not cand:
        return 0

    pilot_norm = _normalize_name(pilot_name)
    if pilot_norm and pilot_norm in cand:
        return 1000 + len(pilot_norm)

    best = 0
    for sn in search_names:
        norm = _normalize_name(sn)
        if norm and norm in cand:
            best = max(best, len(norm))
    return best


def _race_matches_pilot(
    race: dict,
    *,
    year: int,
    pilot_name: str,
    search_names: list[str],
    title_aliases: list[str],
    exclude_names: list[str],
) -> bool:
    name = race.get("name") or ""
    if _is_excluded(name, exclude_names):
        return False

    race_date = race.get("race_date")
    if not race_date or not str(race_date).startswith(f"{year}-"):
        return False

    if title_aliases and _marathongo_title_matches(name, year, title_aliases):
        return True

    if title_aliases:
        return False

    return _match_score(name, search_names, pilot_name) >= 3


def _find_marathongo_date(
    races: list[dict],
    *,
    year: int,
    pilot_name: str,
    search_names: list[str],
    title_aliases: list[str] | None = None,
    exclude_names: list[str] | None = None,
) -> Optional[str]:
    title_aliases = title_aliases or []
    exclude_names = exclude_names or []
    best_date: Optional[str] = None
    best_score = 0

    for race in races:
        name = race.get("name") or ""
        if _is_excluded(name, exclude_names):
            continue

        race_date = race.get("race_date")
        if not race_date or not str(race_date).startswith(f"{year}-"):
            continue

        if title_aliases and _marathongo_title_matches(name, year, title_aliases):
            return str(race_date)[:10]

        if title_aliases:
            continue

        score = _match_score(name, search_names, pilot_name)
        if score > best_score:
            best_score = score
            best_date = str(race_date)[:10]

    return best_date if best_score >= 3 else None


def _lookup_marathongo_slug(pilot: dict[str, Any], year: int) -> Optional[str]:
    from app.services.marathongo_crawler import (
        fetch_marathongo_slug,
        _is_valid_race,
        _fetch_schedule_html,
        _collect_slugs_from_list_html,
    )
    from app.services.race_crawler import HEADERS

    session = requests.Session()
    session.headers.update(HEADERS)

    slug_candidates: list[str] = []

    overrides = pilot.get("slug_overrides") or {}
    if str(year) in overrides:
        slug_candidates.append(str(overrides[str(year)]))

    for tpl in pilot.get("slug_templates") or []:
        slug_candidates.append(tpl.format(year=year))

    keyword = (pilot.get("slug_keyword") or "").lower()
    if keyword:
        try:
            html = _fetch_schedule_html(session, query=pilot.get("search_query") or "")
            for slug in _collect_slugs_from_list_html(html):
                if not slug.startswith(f"{year}-"):
                    continue
                if keyword in slug.lower():
                    slug_candidates.append(slug)
        except Exception as e:
            logger.debug("marathongo slug scan failed: %s", e)

    seen: set[str] = set()
    for slug in slug_candidates:
        if not slug or slug in seen:
            continue
        seen.add(slug)
        try:
            race = fetch_marathongo_slug(slug, session)
        except Exception as e:
            logger.debug("marathongo slug %s failed: %s", slug, e)
            continue

        if not _is_valid_race(race):
            continue

        if _race_matches_pilot(
            race,
            year=year,
            pilot_name=pilot.get("name") or "",
            search_names=pilot.get("search_names") or [],
            title_aliases=pilot.get("title_aliases") or [],
            exclude_names=pilot.get("exclude_names") or [],
        ):
            logger.info("marathongo slug hit: %s -> %s", slug, race.get("race_date"))
            return str(race["race_date"])[:10]

    return None


def _lookup_marathongo_search(
    pilot: dict[str, Any],
    year: int,
    *,
    search_cache: dict[str, list[dict]] | None = None,
) -> Optional[str]:
    query = (pilot.get("search_query") or "").strip()
    if not query:
        return None

    from app.services.marathongo_crawler import search_marathongo

    if search_cache is not None:
        if query not in search_cache:
            try:
                search_cache[query] = search_marathongo(query)
            except Exception as e:
                logger.warning("marathongo search q=%s failed: %s", query, e)
                search_cache[query] = []
        races = search_cache[query]
    else:
        try:
            races = search_marathongo(query)
        except Exception as e:
            logger.warning("marathongo search q=%s failed: %s", query, e)
            return None

    return _find_marathongo_date(
        races,
        year=year,
        pilot_name=pilot.get("name") or "",
        search_names=pilot.get("search_names") or [],
        title_aliases=pilot.get("title_aliases") or [],
        exclude_names=pilot.get("exclude_names") or [],
    )


def _lookup_marathongo(
    pilot: dict[str, Any],
    year: int,
    *,
    races: list[dict] | None = None,
    search_cache: dict[str, list[dict]] | None = None,
    allow_list_fallback: bool = True,
) -> Optional[str]:
    slug_date = _lookup_marathongo_slug(pilot, year)
    if slug_date:
        return slug_date

    search_date = _lookup_marathongo_search(pilot, year, search_cache=search_cache)
    if search_date:
        return search_date

    if not allow_list_fallback:
        return None

    if races is None:
        from app.services.race_crawler import crawl_marathongo
        try:
            races = crawl_marathongo(limit=0)
        except Exception as e:
            logger.warning("marathongo lookup failed: %s", e)
            return None

    return _find_marathongo_date(
        races,
        year=year,
        pilot_name=pilot.get("name") or "",
        search_names=pilot.get("search_names") or [],
        title_aliases=pilot.get("title_aliases") or [],
        exclude_names=pilot.get("exclude_names") or [],
    )


def lookup_pilot_race_date(
    key: str,
    year: int,
    *,
    fetch_external: bool = True,
) -> dict[str, Any]:
    """연도별 race_date 조회. source: catalog | marathongo | null."""
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

    if fetch_external and year <= date.today().year + 1:
        ext = _lookup_marathongo(pilot, year)
        if ext:
            return {
                "key": key,
                "year": year,
                "name": pilot["name"],
                "race_date": ext,
                "source": "marathongo",
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
    rows: list[dict[str, Any]] = []
    search_cache: dict[str, list[dict]] = {}
    today_year = date.today().year

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
                continue

            ext_date = None
            if fetch_external and year <= today_year + 1:
                ext_date = _lookup_marathongo(
                    pilot,
                    year,
                    search_cache=search_cache,
                    allow_list_fallback=False,
                )

            if ext_date:
                rows.append({
                    "key": key,
                    "year": year,
                    "name": pilot["name"],
                    "race_date": ext_date,
                    "source": "marathongo",
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
