"""
marathongo.co.kr 크롤러 — pilot edition 날짜 조회 전용.

roadrun / races 테이블 bulk upsert 용도는 사용하지 않음.
"""
import logging
import re
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MARATHONGO_BASE = "https://www.marathongo.co.kr"


def _shared():
    from app.services.race_crawler import (
        HEADERS,
        _compute_status,
        _get_next_data,
        _normalize_distances,
        _parse_date,
        _parse_won,
    )
    return HEADERS, _compute_status, _get_next_data, _normalize_distances, _parse_date, _parse_won


def _marathongo_from_next_data(page_props: dict) -> dict:
    _, _, _, _normalize_distances, _parse_date, _parse_won = _shared()
    r = (
        page_props.get("raceDetail")
        or page_props.get("race")
        or page_props.get("raceInfo")
        or {}
    )

    race_type_raw = r.get("raceTypeList") or ""
    distances = _normalize_distances(race_type_raw)

    intro = r.get("intro") or ""
    fee_m = re.search(r"참가비\s*(\d{1,3}(?:,\d{3})*)\s*원", intro)
    if not fee_m:
        fee_m = re.search(r"(\d{1,3}(?:,\d{3})+)\s*원", intro)
    entry_fee = _parse_won(fee_m.group(1)) if fee_m else None

    status = None
    if r.get("isSoldOut"):
        status = "접수마감"
    elif r.get("isPaused"):
        status = "일시중단"

    return {
        "name":        r.get("raceName") or r.get("name") or r.get("title"),
        "race_date":   _parse_date(str(r.get("raceDate") or r.get("date") or "")),
        "race_time":   r.get("raceStart") or r.get("startTime") or r.get("time"),
        "location":    r.get("place") or r.get("location") or r.get("venue"),
        "city":        r.get("region") or r.get("city") or r.get("area"),
        "organizer":   r.get("host") or r.get("organizer") or r.get("organization"),
        "distances":   distances,
        "entry_fee":   entry_fee,
        "reg_start":   _parse_date(str(r.get("applicationStartDate") or r.get("regStart") or "")),
        "reg_end":     _parse_date(str(r.get("applicationEndDate") or r.get("regEnd") or "")),
        "status":      status,
        "website_url": r.get("homepageUrl") or r.get("homepage") or r.get("website"),
    }


def _marathongo_from_html(soup: BeautifulSoup) -> dict:
    _, _, _, _normalize_distances, _parse_date, _parse_won = _shared()
    text = soup.get_text(" ", strip=True)

    name = None
    og_title = soup.find("meta", property="og:title")
    if og_title:
        raw = str(og_title.get("content") or "").strip()
        name = raw.split("|")[0].strip() or None

    race_date = None
    dm = re.search(r"(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}", text)
    if dm:
        race_date = dm.group(1)
    if not race_date:
        dm2 = re.search(r"\d{4}년\s*\d{1,2}월\s*\d{1,2}일", text)
        if dm2:
            race_date = _parse_date(dm2.group(0))

    time_m = re.search(r"\d{4}-\d{2}-\d{2}\s+(\d{2}:\d{2})", text)
    race_time = time_m.group(1) if time_m else None

    dist_ctx = ""
    ctx_m = re.search(r"(?:종목|코스|거리).{0,100}", text)
    if ctx_m:
        dist_ctx = ctx_m.group(0)
    distances = _normalize_distances(dist_ctx) if dist_ctx else []

    fee_m = re.search(r"참가비\s*(\d{1,3}(?:,\d{3})*)\s*원", text)
    if not fee_m:
        fee_m = re.search(r"(\d{1,3}(?:,\d{3})+)\s*원", text)
    entry_fee = _parse_won(fee_m.group(1)) if fee_m else None

    reg_m = re.search(
        r"(\d{4}[.\-]\d{1,2}[.\-]\d{1,2})\s*[~～]\s*(\d{4}[.\-]\d{1,2}[.\-]\d{1,2})",
        text,
    )
    return {
        "name":      name,
        "race_date": race_date,
        "race_time": race_time,
        "distances": distances,
        "entry_fee": entry_fee,
        "reg_start": _parse_date(reg_m.group(1)) if reg_m else None,
        "reg_end":   _parse_date(reg_m.group(2)) if reg_m else None,
    }


def _fetch_marathongo_detail(slug: str, session: requests.Session) -> dict:
    HEADERS, _compute_status, _get_next_data, _, _, _ = _shared()
    url = f"{MARATHONGO_BASE}/raceDetail/domestic/{slug}"
    try:
        resp = session.get(url, timeout=15)
        resp.encoding = "utf-8"
        resp.raise_for_status()
    except Exception as e:
        logger.warning("marathongo 상세 실패: %s — %s", url, e)
        return {}

    race: dict = {}
    data = _get_next_data(resp.text)
    if data:
        try:
            race = _marathongo_from_next_data(data["props"]["pageProps"])
        except (KeyError, TypeError):
            pass

    if not race.get("name"):
        soup = BeautifulSoup(resp.text, "html.parser")
        race = _marathongo_from_html(soup)

    race["source_url"] = url
    race["source"] = "marathongo"
    race["slug"] = slug
    if not race.get("status"):
        race["status"] = _compute_status(race)
    elif _compute_status(race) == "종료":
        race["status"] = "종료"
    return race


def _is_valid_race(race: dict) -> bool:
    name = (race.get("name") or "").strip()
    if not name or not race.get("race_date"):
        return False
    if "마라톤GO" in name or name == "마라톤 GO":
        return False
    return True


def fetch_marathongo_slug(slug: str, session: requests.Session | None = None) -> dict:
    """slug 직접 조회 — 목록에 없는 과거 대회(예: 2026-seoul-international-marathon)."""
    HEADERS, _, _, _, _, _ = _shared()
    if session is None:
        session = requests.Session()
        session.headers.update(HEADERS)
    return _fetch_marathongo_detail(slug, session)


def _collect_slugs_from_list_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = soup.find_all("a", href=re.compile(r"/raceDetail/domestic/"))
    return list(dict.fromkeys(
        str(a["href"]).split("/raceDetail/domestic/")[1].rstrip("/")
        for a in links
    ))


def _normalize_blob(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def _slugs_matching_query(html: str, query: str) -> list[str]:
    """목록 HTML에서 q 필터(클라이언트) — 링크 텍스트·slug에 검색어 포함."""
    q = _normalize_blob(query)
    if not q:
        return []

    soup = BeautifulSoup(html, "html.parser")
    slugs: list[str] = []
    for a in soup.find_all("a", href=re.compile(r"/raceDetail/domestic/")):
        slug = str(a["href"]).split("/raceDetail/domestic/")[1].rstrip("/")
        blob = _normalize_blob(a.get_text(" ", strip=True) + slug)
        if q in blob:
            slugs.append(slug)
    return list(dict.fromkeys(slugs))


def _fetch_schedule_html(
    session: requests.Session,
    *,
    query: str = "",
    race_end: str = "전체",
) -> str:
    if query.strip():
        url = (
            f"{MARATHONGO_BASE}/raceSchedule/domestic"
            f"?q={quote(query.strip())}&raceEnd={quote(race_end)}"
        )
    else:
        url = f"{MARATHONGO_BASE}/raceSchedule/domestic"
    resp = session.get(url, timeout=15)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    return resp.text


def search_marathongo(
    query: str,
    *,
    race_end: str = "전체",
    limit: int = 0,
    session: requests.Session | None = None,
) -> list[dict]:
    """marathongo 국내 일정 검색 — q={검색어}&raceEnd=전체.

    예: https://marathongo.co.kr/raceSchedule/domestic?q=경주&raceEnd=전체
    """
    if not query.strip():
        return []

    HEADERS, _, _, _, _, _ = _shared()
    if session is None:
        session = requests.Session()
        session.headers.update(HEADERS)

    try:
        html = _fetch_schedule_html(session, query=query, race_end=race_end)
    except Exception as e:
        logger.warning("marathongo search failed q=%s: %s", query, e)
        return []

    slugs = _slugs_matching_query(html, query)
    if not slugs:
        slugs = _collect_slugs_from_list_html(html)
    if limit > 0:
        slugs = slugs[:limit]

    results: list[dict] = []
    for slug in slugs:
        race = _fetch_marathongo_detail(slug, session)
        if _is_valid_race(race):
            results.append(race)

    logger.info("marathongo search q=%s: %d건 (slugs=%d)", query, len(results), len(slugs))
    return results


def crawl_marathongo(limit: int = 30) -> list[dict]:
    """marathongo 국내 대회 목록+상세 수집. limit=0 이면 slug 제한 없음."""
    HEADERS, _, _get_next_data, _, _, _ = _shared()
    session = requests.Session()
    session.headers.update(HEADERS)

    list_url = f"{MARATHONGO_BASE}/raceSchedule/domestic"
    try:
        resp = session.get(list_url, timeout=15)
        resp.encoding = "utf-8"
        resp.raise_for_status()
    except Exception as e:
        logger.error("marathongo 목록 실패: %s", e)
        return []

    slugs = _collect_slugs_from_list_html(resp.text)
    if limit > 0:
        slugs = slugs[:limit]

    if not slugs:
        data = _get_next_data(resp.text)
        if data:
            try:
                races_raw = data["props"]["pageProps"].get("races") or []
                slugs = [
                    r.get("slug") or str(r.get("id"))
                    for r in races_raw
                    if r.get("slug") or r.get("id")
                ]
                if limit > 0:
                    slugs = slugs[:limit]
            except (KeyError, TypeError):
                pass

    results = []
    for slug in slugs:
        race = _fetch_marathongo_detail(slug, session)
        if _is_valid_race(race):
            results.append(race)

    logger.info("marathongo 수집: %d건 (slugs=%d)", len(results), len(slugs))
    return results
