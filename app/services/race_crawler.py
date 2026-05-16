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
    """날짜 기반 접수/진행 상태 계산"""
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


# 거리/종목 토큰 추출 패턴 (긴/구체적 패턴 우선)
_DIST_PATTERN = re.compile(
    r"풀코스|풀마라톤|마라톤풀|하프마라톤|마라톤하프"
    r"|마라톤\d+(?:\.\d+)?(?:km|KM|Km|K|k|m|마일)"  # 마라톤10km, 마라톤100km 등
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
    """숫자+단위 → XK / X마일 포맷. 비현실적 거리는 연도 제거 후 재시도."""
    num = float(num_str)

    # 비현실적으로 큰 숫자 → 연도(202x) 접두사가 붙은 경우 제거
    # 예: 202610 → 2026 + 10, 20265 → 2026 + 5
    if num > 300:
        year_m = re.match(r"^(202\d)(\d+(?:\.\d+)?)$", num_str)
        if year_m:
            num_str = year_m.group(2)
            num = float(num_str)
        else:
            return None  # 연도 패턴도 아니면 무시

    label = str(int(num)) if num == int(num) else num_str

    if unit.lower() == "마일":
        return f"{label}마일"
    return f"{label}K"


def _normalize_distances(raw) -> list[str]:
    """거리/종목을 풀/하프/XK/걷기 형태로 정규화.

    실제 DB 데이터 기반 처리 케이스:
    - 마라톤하프 → 하프 / 마라톤풀 → 풀
    - 마라톤10km → 10K  (마라톤 접두사 + 숫자)
    - 202610km  → 10K  (연도 2026 접두사 제거)
    - 50K50K    → 50K  (중복 토큰 제거)
    - 36Km      → 36K  (단위 대소문자 통일)
    - 3km걷기   → 3K, 걷기 (복합 토큰 분리)
    - 100마일   → 100마일
    """
    combined = ",".join(str(x) for x in raw) if isinstance(raw, list) else str(raw or "")

    seen: set[str] = set()
    result: list[str] = []

    for token in _DIST_PATTERN.findall(combined):
        t = token.strip()

        # 1) 단어형 (풀/하프/걷기)
        normalized: Optional[str] = _WORD_TO_NORM.get(t)

        # 2) 마라톤+숫자형: "마라톤10km" → "10K"
        if normalized is None:
            m = re.match(r"^마라톤(\d+(?:\.\d+)?)(km|KM|Km|K|k|m|마일)$", t, re.IGNORECASE)
            if m:
                normalized = _format_dist_num(m.group(1), m.group(2))

        # 3) 순수 숫자+단위형
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
    # raceDetail 키 우선 (실제 API 응답 구조)
    r = (
        page_props.get("raceDetail")
        or page_props.get("race")
        or page_props.get("raceInfo")
        or {}
    )

    # raceTypeList: "하프,10km,5km" 형식
    race_type_raw = r.get("raceTypeList") or ""
    distances = _normalize_distances(race_type_raw)

    # intro 텍스트에서 참가비 추출
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

    # 대회명: og:title에서 " | 마라톤GO" 제거
    name = None
    og_title = soup.find("meta", property="og:title")
    if og_title:
        raw = str(og_title.get("content") or "").strip()
        name = raw.split("|")[0].strip() or None

    # 날짜: "2026-05-16" 형식 우선, 한국어 형식 fallback
    race_date = None
    dm = re.search(r"(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}", text)  # "2026-05-16 08:30" 패턴
    if dm:
        race_date = dm.group(1)
    if not race_date:
        dm2 = re.search(r"\d{4}년\s*\d{1,2}월\s*\d{1,2}일", text)
        if dm2:
            race_date = _parse_date(dm2.group(0))

    # 시작 시간: 날짜 바로 뒤 HH:MM
    time_m = re.search(r"\d{4}-\d{2}-\d{2}\s+(\d{2}:\d{2})", text)
    race_time = time_m.group(1) if time_m else None

    # 거리: "종목/코스/거리" 키워드 주변 100자만 스캔 (전체 텍스트 오탐 방지)
    dist_ctx = ""
    ctx_m = re.search(r"(?:종목|코스|거리).{0,100}", text)
    if ctx_m:
        dist_ctx = ctx_m.group(0)
    distances = _normalize_distances(dist_ctx) if dist_ctx else []

    # 참가비: "참가비 20,000원" 또는 "20,000원" 패턴
    fee_m = re.search(r"참가비\s*(\d{1,3}(?:,\d{3})*)\s*원", text)
    if not fee_m:
        fee_m = re.search(r"(\d{1,3}(?:,\d{3})+)\s*원", text)
    entry_fee = _parse_won(fee_m.group(1)) if fee_m else None

    # 접수 기간
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
    # isSoldOut/isPaused 플래그가 없으면 날짜 기반 상태로 채움
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

    # 대회명 (목록 페이지에서 잘린 이름을 상세 페이지로 교정)
    if raw.get("name"):
        result["name"] = raw["name"]

    # 출발시간: "2026년3월21일 출발시간:오전 09:00"
    dt_raw = raw.get("datetime_raw", "")
    tm = re.search(r"출발시간[:\s]*(오전|오후)\s*(\d{1,2}):(\d{2})", dt_raw)
    if tm:
        meridiem, h, minute = tm.group(1), int(tm.group(2)), tm.group(3)
        if meridiem == "오후" and h < 12:
            h += 12
        elif meridiem == "오전" and h == 12:
            h = 0
        result["race_time"] = f"{h:02d}:{minute}"

    # 대회종목 → distances
    dist_raw = raw.get("distances_raw", "")
    if dist_raw:
        result["distances"] = _normalize_distances(dist_raw)

    # 지역 / 장소 / 주최
    for field in ("city", "location", "organizer"):
        if raw.get(field):
            result[field] = raw[field]

    # 접수기간: "2026년1월24일~2026년2월22일"
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

    # 전체 tr 스캔 → 첫 번째 셀이 M/D 날짜 패턴인 행만 추출
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
                # onclick 또는 href 내 open_window('win', 'view.php?no=123', ...) 파싱
                onclick = str(link.get("onclick", "")) or raw_href
                om = re.search(r"open_window\([^,]+,\s*['\"]([^'\"]+)['\"]", onclick)
                if om:
                    href = om.group(1)
        # urljoin으로 상대경로 안전하게 결합 (슬래시 누락 방지)
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

    # 상세 페이지 병렬 수집 (최대 8 workers)
    def enrich(race: dict) -> dict:
        detail = _fetch_roadrun_detail(race["source_url"], session)
        merged = {**race, **detail}
        merged["status"] = _compute_status(merged)
        return merged

    with ThreadPoolExecutor(max_workers=8) as executor:
        enriched = list(executor.map(enrich, races))

    return enriched


# ── 통합 ─────────────────────────────────────────────────────────────────────

def crawl_all(limit: int = 30) -> list[dict]:
    races: list[dict] = []
    races.extend(crawl_marathongo(limit=limit))
    races.extend(crawl_roadrun(limit=limit))
    return races
