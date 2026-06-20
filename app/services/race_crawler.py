"""
대회 정보 크롤러 (app/services/race_crawler.py)

World Athletics Label Road Races (GraphQL) 수집 및 pilot 관련 유틸.

marathongo.co.kr / roadrun.co.kr 크롤러는 2026-06 사용 중단 — crawl_* stub은 [] 반환.
"""
import re
import json
import logging
import requests
import anthropic
from bs4 import BeautifulSoup
from typing import Optional
from datetime import date, datetime

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}


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



# ── marathongo.co.kr / roadrun.or.kr (비활성 — catalog·Admin 수동 입력) ─────
# 레거시 구현: app/services/_legacy_domestic_crawlers.py (참고용 보관)


def crawl_marathongo(limit: int = 30) -> list[dict]:
    """marathongo.co.kr 크롤링 비활성. 빈 목록 반환."""
    logger.info("crawl_marathongo disabled (use pilot catalog / Admin manual dates)")
    return []


def crawl_roadrun(limit: int = 30) -> list[dict]:
    """roadrun.or.kr 크롤링 비활성. 빈 목록 반환."""
    logger.info("crawl_roadrun disabled (use pilot catalog / Admin manual dates)")
    return []


def crawl_all(limit: int = 30) -> list[dict]:
    """국내 사이트 통합 크롤링 비활성."""
    return []



# ── World Athletics Label Road Races (공식 GraphQL) ───────────────────────────

_WA_EDITION_PREFIX = re.compile(r"^\d+\.\s*")


def map_wa_label(
    ranking_category: Optional[str],
    competition_subgroup: Optional[str],
) -> str:
    """competitionSubgroup 우선, rankingCategory 보조."""
    subgroup = (competition_subgroup or "").strip().lower()
    if "platinum" in subgroup:
        return "platinum"
    if subgroup == "gold":
        return "gold"
    if subgroup == "elite":
        return "elite"
    if subgroup in ("label", "silver", "bronze"):
        return "label"

    cat = (ranking_category or "").strip().upper()
    if cat in ("GW", "GL"):
        return "platinum"
    if cat in ("A", "B"):
        return "gold"
    if cat == "C":
        return "elite"
    return "label"


def parse_wa_venue(venue: str) -> tuple[str, str]:
    """'Schwäbisch Hall (GER)' → (city, ISO3 country code)."""
    if not venue:
        return "", ""
    m = re.match(r"^(.+?)\s*\(([A-Za-z]{3})\)\s*$", venue.strip())
    if m:
        return m.group(1).strip(), m.group(2).upper()
    return venue.strip(), ""


def normalize_wa_name_en(name: str) -> str:
    """회차 접두사 제거 — 마스터 매칭용."""
    return _WA_EDITION_PREFIX.sub("", (name or "").strip())


def parse_wa_race_date(date_str: str, year: int) -> Optional[str]:
    """WA 날짜 문자열 → ISO. GraphQL startDate 또는 Wikipedia '17 Mar' 형식."""
    if not date_str:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str.strip()):
        return date_str.strip()
    date_str = date_str.split("–")[0].split("-")[0].strip()
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(f"{date_str} {year}", fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _wa_event_to_dict(
    event: dict,
    *,
    season: int,
    organiser: Optional[dict] = None,
) -> dict:
    venue = event.get("venue") or ""
    city, country_code = parse_wa_venue(venue)
    if not country_code:
        country_code = (event.get("country") or "").upper()

    name_raw = (event.get("name") or "").strip()
    name_en = normalize_wa_name_en(name_raw)
    comp_id = event.get("id")
    start_date = event.get("startDate") or ""
    end_date = event.get("endDate") or ""

    from app.services.wa_graphql import result_page_url

    row: dict = {
        "wa_competition_id": comp_id,
        "date": event.get("dateRange") or start_date,
        "name": name_raw,
        "name_en": name_en,
        "city": city,
        "country": country_code,
        "venue": venue,
        "location": venue,
        "race_date": start_date or None,
        "end_date": end_date or None,
        "year": int(start_date[:4]) if start_date and len(start_date) >= 4 else season,
        "wa_label": map_wa_label(
            event.get("rankingCategory"),
            event.get("competitionSubgroup"),
        ),
        "ranking_category": event.get("rankingCategory"),
        "competition_subgroup": event.get("competitionSubgroup"),
        "source": "world_athletics",
        "source_url": result_page_url(comp_id) if comp_id else "",
    }

    if organiser:
        row["website_url"] = organiser.get("websiteUrl") or organiser.get("resultsPageUrl")
        row["official_url"] = organiser.get("websiteUrl") or organiser.get("resultsPageUrl")
        contacts = organiser.get("contactPersons") or []
        if contacts:
            row["organizer"] = contacts[0].get("name") or ""

    return row


def crawl_wa_label_races(
    year: int,
    *,
    fetch_organiser: bool = False,
    cancel_check=None,
) -> list[dict]:
    """World Athletics Label Road Races 캘린더를 GraphQL로 수집한다.

    URL: https://worldathletics.org/competitions/world-athletics-label-road-races/calendar-results
    API: getMinisiteCalendarEvents (competitionGroupId=3775, season=year)
    반환 필드: wa_competition_id, date, name, name_en, city, country, wa_label,
               race_date, year, source, source_url, (+ official_url/organizer)

    fetch_organiser=True 이면 hasCompetitionInformation 이벤트에
    getCompetitionOrganiserInfo 추가 호출 (주최자·공식 URL).
    """
    from app.services.wa_graphql import fetch_minisite_calendar, fetch_organiser_info

    try:
        events = fetch_minisite_calendar(year)
    except Exception as e:
        logger.error("WA GraphQL calendar fetch failed (%s): %s", year, e)
        return []

    races: list[dict] = []
    for i, event in enumerate(events):
        if cancel_check and i % 10 == 0:
            cancel_check()
        organiser = None
        if fetch_organiser and event.get("hasCompetitionInformation") and event.get("id"):
            organiser = fetch_organiser_info(int(event["id"]))
        races.append(_wa_event_to_dict(event, season=year, organiser=organiser))

    logger.info("WA Label Road Races (%s): %d events", year, len(races))
    return races


def _translate_batch(names_en: list[str], client) -> list[str]:
    """영문 대회명 배치를 한국어로 번역. 실패 시 원문 반환."""
    prompt = (
        "다음 마라톤/러닝 대회 영문명을 한국어로 번역해 JSON 문자열 배열로만 응답하세요.\n"
        "응답 형식: [\"한국어명1\", \"한국어명2\", ...]\n"
        "규칙:\n"
        "- 잘 알려진 대회는 공식 한국어 표기 사용 (예: Tokyo Marathon → 도쿄마라톤)\n"
        "- 생소한 대회는 '도시명+마라톤/대회' 형식으로 번역\n"
        "- 객체(dict) 금지, 반드시 문자열만 포함\n"
        "- 코드블록 없이 순수 JSON 배열만 출력\n"
        f"- 반드시 {len(names_en)}개 항목 출력\n\n"
        + json.dumps(names_en, ensure_ascii=False)
    )
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        parsed = json.loads(raw)
        # dict 응답 방어: {"0": "이름", ...} 형태면 values 추출
        if isinstance(parsed, dict):
            parsed = list(parsed.values())
        names_ko = [
            v if isinstance(v, str)
            else v.get("korean") or v.get("ko") or v.get("name") or next(iter(v.values()), "")
            for v in parsed
        ]
        if len(names_ko) == len(names_en):
            return names_ko
        logger.warning(f"번역 배치 수 불일치: 입력 {len(names_en)} / 결과 {len(names_ko)} — 원문 유지")
    except Exception as e:
        logger.warning(f"번역 배치 실패: {e} — 원문 유지")
    return names_en


def translate_race_names_to_korean(
    races: list[dict],
    batch_size: int = 50,
    cancel_check=None,
) -> list[dict]:
    """WA 영문 대회명을 한국어로 일괄 번역 (Claude Haiku, 50개씩 배치).

    각 race dict에 name_en(원문) 필드를 추가하고, name을 한국어로 교체한다.
    배치 단위로 처리하므로 일부 실패 시 해당 배치만 영문명 유지한다.
    """
    if not races:
        return races

    from app.core.config import settings
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    names_ko_all: list[str] = []
    names_en_all = [r.get("name_en") or r.get("name") or "" for r in races]

    for i in range(0, len(names_en_all), batch_size):
        if cancel_check:
            cancel_check()
        batch = names_en_all[i: i + batch_size]
        names_ko_all.extend(_translate_batch(batch, client))
        logger.info(f"WA 번역 진행: {min(i + batch_size, len(races))}/{len(races)}")

    for i, race in enumerate(races):
        if not race.get("name_en"):
            race["name_en"] = names_en_all[i]
        race["name"] = names_ko_all[i]

    return races
