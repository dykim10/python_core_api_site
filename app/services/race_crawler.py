"""
대회 정보 크롤러 (app/services/race_crawler.py)

marathongo.co.kr 와 roadrun.co.kr 에서 마라톤/러닝 대회 정보를 수집한다.
race_info.py 라우터에서 호출하며, 수집 결과를 dict 리스트로 반환한다.

[크롤러 구성]
  crawl_marathongo(limit)
    - 목록 페이지 HTML 에서 상세 페이지 slug 목록 추출
    - 상세 페이지의 __NEXT_DATA__ JSON 우선 파싱 (Next.js SSR 구조)
    - __NEXT_DATA__ 없으면 HTML fallback 파싱 (_marathongo_from_html)

  crawl_roadrun(limit)
    - 목록 테이블에서 대회 기본 정보 추출
    - ThreadPoolExecutor(max_workers=8) 로 상세 페이지 병렬 수집
    - 인코딩 euc-kr, SSL 인증서 무시(verify=False) — 구형 사이트

  crawl_all(limit)
    - 두 소스를 합친 뒤 _dedup_races 로 중복 제거 후 반환

[중복 제거 전략 — _dedup_races]
  race_date 가 같은 대회 중 이름 유사도 >= 0.7 이면 동일 대회로 판단.
  marathongo 를 기준(base)으로, roadrun 으로 null 필드를 보완(supplement).
  _name_similarity: 연도/회차/마라톤 등 노이즈 제거 후 공통 문자 비율로 계산.

[공통 유틸]
  _normalize_distances : "풀코스", "42.195km", "10K" 등 → 풀/하프/XK/걷기 통일
  _compute_status      : race_date / reg_start / reg_end 기준 접수상태 계산
  _parse_date          : 한국어("2025년 5월 24일") / 구분자 혼용 → "YYYY-MM-DD"
  _get_next_data       : <script id="__NEXT_DATA__"> 추출 → dict 반환
"""
import re
import json
import logging
import urllib3
import requests
from bs4 import BeautifulSoup, Comment
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}
MARATHONGO_BASE = "https://marathongo.co.kr"
ROADRUN_BASE    = "http://www.roadrun.co.kr"


# ── 공통 유틸 ─────────────────────────────────────────────────────────────────

def _compute_status(race: dict) -> str:
    today = date.today()

    def _d(val) -> Optional[date]:
        try:
            return date.fromisoformat(str(val)) if val else None
        except (ValueError, TypeError):
            return None

    race_date = _d(race.get("race_date"))
    reg_start = _d(race.get("reg_start"))
    reg_end   = _d(race.get("reg_end"))

    if race_date and race_date < today:
        return "종료"
    if reg_end and reg_end < today:
        return "접수마감"
    if reg_start and reg_end and reg_start <= today <= reg_end:
        return "접수중"
    return "접수전"


def _get_next_data(html: str) -> Optional[dict]:
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id="__NEXT_DATA__")
    return json.loads(tag.string or "{}") if tag else None


def _parse_date(text: str) -> Optional[str]:
    if not text:
        return None
    for pattern in (
        r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일",
        r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})",
    ):
        m = re.search(pattern, text)
        if m:
            try:
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                return d.isoformat()
            except ValueError:
                continue
    return None


def _parse_won(text: str) -> Optional[int]:
    if not text:
        return None
    nums = re.sub(r"[^\d]", "", text)
    return int(nums) if nums else None


# ── 거리/종목 정규화 ──────────────────────────────────────────────────────────

_DIST_PATTERN = re.compile(
    r"풀코스|풀마라톤|마라톤풀|하프마라톤|마라톤하프"
    r"|마라톤\d+(?:\.\d+)?(?:km|KM|Km|K|k|m|마일)"
    r"|풀|하프|마라톤"
    r"|걷기코스|걷기"
    r"|\d+(?:\.\d+)?(?:km|KM|Km|K|k|m|마일)"
)

_WORD_TO_NORM: dict[str, str] = {
    "풀코스": "풀", "풀마라톤": "풀", "마라톤풀": "풀",
    "풀": "풀", "마라톤": "풀",
    "하프마라톤": "하프", "마라톤하프": "하프", "하프": "하프",
    "걷기코스": "걷기", "걷기": "걷기",
}


def _format_dist_num(num_str: str, unit: str) -> Optional[str]:
    num = float(num_str)
    if num > 300:
        year_m = re.match(r"^(202\d)(\d+(?:\.\d+)?)$", num_str)
        if year_m:
            num_str = year_m.group(2)
            num = float(num_str)
        else:
            return None
    label = str(int(num)) if num == int(num) else num_str
    if unit.lower() == "마일":
        return f"{label}마일"
    return f"{label}K"


def _normalize_distances(raw) -> list[str]:
    """거리/종목을 풀/하프/XK/걷기 형태로 정규화."""
    combined = ",".join(str(x) for x in raw) if isinstance(raw, list) else str(raw or "")

    seen: set[str] = set()
    result: list[str] = []

    for token in _DIST_PATTERN.findall(combined):
        t = token.strip()

        normalized: Optional[str] = _WORD_TO_NORM.get(t)

        if normalized is None:
            m = re.match(r"^마라톤(\d+(?:\.\d+)?)(km|KM|Km|K|k|m|마일)$", t, re.IGNORECASE)
            if m:
                normalized = _format_dist_num(m.group(1), m.group(2))

        if normalized is None:
            m = re.match(r"^(\d+(?:\.\d+)?)(km|KM|Km|K|k|m|마일)$", t, re.IGNORECASE)
            if m:
                normalized = _format_dist_num(m.group(1), m.group(2))

        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)

    return result


# ── marathongo.co.kr ──────────────────────────────────────────────────────────

def _marathongo_from_next_data(page_props: dict) -> dict:
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
    """__NEXT_DATA__ 파싱 실패 시 HTML fallback"""
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

    # "종목/코스/거리" 키워드 주변 100자만 스캔 (전체 텍스트 오탐 방지)
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
    url = f"{MARATHONGO_BASE}/raceDetail/domestic/{slug}"
    try:
        resp = session.get(url, timeout=15)
        resp.encoding = "utf-8"
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"marathongo 상세 실패: {url} — {e}")
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
    if not race.get("status"):
        race["status"] = _compute_status(race)
    elif _compute_status(race) == "종료":
        race["status"] = "종료"
    return race


def crawl_marathongo(limit: int = 30) -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)

    list_url = f"{MARATHONGO_BASE}/raceSchedule/domestic"
    try:
        resp = session.get(list_url, timeout=15)
        resp.encoding = "utf-8"
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"marathongo 목록 실패: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    links = soup.find_all("a", href=re.compile(r"/raceDetail/domestic/"))
    slugs: list[str] = list(dict.fromkeys(
        str(a["href"]).split("/raceDetail/domestic/")[1].rstrip("/")
        for a in links
    ))[:limit]

    if not slugs:
        data = _get_next_data(resp.text)
        if data:
            try:
                races_raw = data["props"]["pageProps"].get("races") or []
                slugs = [
                    r.get("slug") or str(r.get("id"))
                    for r in races_raw
                    if r.get("slug") or r.get("id")
                ][:limit]
            except (KeyError, TypeError):
                pass

    results = []
    for slug in slugs:
        race = _fetch_marathongo_detail(slug, session)
        if race.get("name") and race.get("race_date"):
            results.append(race)

    return results


# ── roadrun.co.kr ─────────────────────────────────────────────────────────────

def _roadrun_split_name_dist(text: str) -> tuple[str, list[str]]:
    """대회명+거리 합쳐진 텍스트 분리. 예: "제26회 여성마라톤10km,5km,3km걷기" """
    m = re.search(
        r"((?:풀코스|풀마라톤|마라톤풀|하프마라톤|마라톤하프|풀|하프|마라톤|걷기코스|걷기"
        r"|\d+(?:\.\d+)?(?:km|KM|K|k|m|마일))"
        r"(?:[,\s]*(?:풀코스|풀마라톤|마라톤풀|하프마라톤|마라톤하프|풀|하프|마라톤|걷기코스|걷기"
        r"|\d+(?:\.\d+)?(?:km|KM|K|k|m|마일)))*)\s*$",
        text,
        re.IGNORECASE,
    )
    if m:
        name = text[: m.start()].strip()
        distances = _normalize_distances(m.group(1))
        return name, distances
    return text, []


def _parse_roadrun_detail(html: str) -> dict:
    """roadrun.co.kr view.php 팝업 페이지 파싱"""
    soup = BeautifulSoup(html, "html.parser")

    label_map = {
        "대회명":   "name",
        "대회일시": "datetime_raw",
        "대회종목": "distances_raw",
        "대회지역": "city",
        "대회장소": "location",
        "주최단체": "organizer",
        "접수기간": "reg_period",
        "홈페이지": "website_url",
    }
    raw: dict = {}
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True)
        if label not in label_map:
            continue
        key = label_map[label]
        if label == "홈페이지":
            a = cells[1].find("a")
            raw[key] = str(a.get("href", "")).strip() if a else cells[1].get_text(strip=True)
        else:
            raw[key] = cells[1].get_text(" ", strip=True)

    result: dict = {}

    if raw.get("name"):
        result["name"] = raw["name"]

    dt_raw = raw.get("datetime_raw", "")
    tm = re.search(r"출발시간[:\s]*(오전|오후)\s*(\d{1,2}):(\d{2})", dt_raw)
    if tm:
        meridiem, h, minute = tm.group(1), int(tm.group(2)), tm.group(3)
        if meridiem == "오후" and h < 12:
            h += 12
        elif meridiem == "오전" and h == 12:
            h = 0
        result["race_time"] = f"{h:02d}:{minute}"

    dist_raw = raw.get("distances_raw", "")
    if dist_raw:
        result["distances"] = _normalize_distances(dist_raw)

    for field in ("city", "location", "organizer"):
        if raw.get(field):
            result[field] = raw[field]

    rp = raw.get("reg_period", "")
    rm = re.search(
        r"(\d{4}년\s*\d{1,2}월\s*\d{1,2}일)\s*[~～]\s*(\d{4}년\s*\d{1,2}월\s*\d{1,2}일)", rp
    )
    if rm:
        result["reg_start"] = _parse_date(rm.group(1))
        result["reg_end"] = _parse_date(rm.group(2))

    if raw.get("website_url"):
        result["website_url"] = raw["website_url"]

    return result


def _fetch_roadrun_detail(url: str, session: requests.Session) -> dict:
    try:
        resp = session.get(url, verify=False, timeout=15)
        resp.encoding = "euc-kr"
        resp.raise_for_status()
        return _parse_roadrun_detail(resp.text)
    except Exception as e:
        logger.warning(f"roadrun 상세 실패: {url} — {e}")
        return {}


def crawl_roadrun(limit: int = 0) -> list[dict]:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    url = f"{ROADRUN_BASE}/schedule/list.php"
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        resp = session.get(url, verify=False, timeout=15)
        resp.encoding = "euc-kr"
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"roadrun fetch 실패: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    page_text = soup.get_text()
    year_m = re.search(r"(20\d{2})년", page_text)
    current_year = int(year_m.group(1)) if year_m else 2026

    seen_urls: set[str] = set()
    races = []
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        date_text = cells[0].get_text(strip=True)
        dm = re.match(r"^(\d{1,2})/(\d{1,2})", date_text)
        if not dm:
            continue

        name_raw  = cells[1].get_text(strip=True)
        location  = cells[2].get_text(strip=True)
        org_phone = cells[3].get_text(strip=True)

        if not name_raw:
            continue

        race_date = f"{current_year}-{int(dm.group(1)):02d}-{int(dm.group(2)):02d}"
        name, distances = _roadrun_split_name_dist(name_raw)
        organizer = re.sub(r"☎.*$", "", org_phone).strip()

        link = cells[1].find("a") or cells[0].find("a")
        href = ""
        if link:
            raw_href = str(link.get("href", ""))
            if raw_href and not raw_href.lower().startswith("javascript"):
                href = raw_href
            else:
                onclick = str(link.get("onclick", "")) or raw_href
                om = re.search(r"open_window\([^,]+,\s*['\"]([^'\"]+)['\"]", onclick)
                if om:
                    href = om.group(1)
        source_url = urljoin(url, href) if href else f"{url}?key={race_date}_{name[:20]}"

        if source_url in seen_urls:
            continue
        seen_urls.add(source_url)

        if name and race_date:
            races.append({
                "name":       name,
                "race_date":  race_date,
                "location":   location,
                "distances":  distances,
                "organizer":  organizer,
                "source":     "roadrun",
                "source_url": source_url,
            })

    if not races:
        logger.warning("roadrun: 레이스 데이터 없음")
        return []

    if limit > 0:
        races = races[:limit]

    def enrich(race: dict) -> dict:
        detail = _fetch_roadrun_detail(race["source_url"], session)
        merged = {**race, **detail}
        merged["status"] = _compute_status(merged)
        return merged

    with ThreadPoolExecutor(max_workers=8) as executor:
        enriched = list(executor.map(enrich, races))

    return enriched


# ── 통합 ─────────────────────────────────────────────────────────────────────

def _core_name(name: str) -> str:
    t = name or ""
    t = re.sub(r"20\d{2}", "", t)
    t = re.sub(r"제\s*\d+\s*회", "", t)
    t = re.sub(r"[^가-힣a-zA-Z0-9]", "", t)
    t = re.sub(r"마라톤|대회|마라|런|RUN|run", "", t, flags=re.IGNORECASE)
    return t.strip().lower()


def _name_similarity(a: str, b: str) -> float:
    ca, cb = _core_name(a), _core_name(b)
    if not ca or not cb:
        return 0.0
    if ca in cb or cb in ca:
        return 1.0
    shorter, longer = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    common = sum(1 for c in shorter if c in longer)
    return common / len(longer)


def _merge_race(base: dict, supplement: dict) -> dict:
    merged = dict(base)
    for key, val in supplement.items():
        if key in ("source", "source_url"):
            continue
        if merged.get(key) is None and val is not None:
            merged[key] = val
    return merged


def _dedup_races(marathongo: list[dict], roadrun: list[dict]) -> list[dict]:
    """날짜 + 대회명 유사도 기반 중복 제거. marathongo 우선, roadrun으로 null 필드 보완."""
    result = list(marathongo)
    THRESHOLD = 0.7

    for rr in roadrun:
        rr_date = rr.get("race_date")
        matched = None
        for mg in marathongo:
            if mg.get("race_date") != rr_date:
                continue
            if _name_similarity(mg.get("name", ""), rr.get("name", "")) >= THRESHOLD:
                matched = mg
                break

        if matched:
            idx = result.index(matched)
            result[idx] = _merge_race(matched, rr)
            logger.debug(f"중복 병합: {matched.get('name')} ← {rr.get('name')}")
        else:
            result.append(rr)

    return result


def crawl_all(limit: int = 30) -> list[dict]:
    mg_races = crawl_marathongo(limit=limit)
    rr_races = crawl_roadrun(limit=limit)
    return _dedup_races(mg_races, rr_races)
