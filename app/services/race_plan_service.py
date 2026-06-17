"""
레이스 플랜 생성 서비스 (app/services/race_plan_service.py)

race_edition + 날씨 + 코스 + RAG 유사 케이스를 조합해
Claude API(claude-opus-4-8)로 개인화 레이스 플랜을 생성한다.

[데이터 흐름]
  1. race_editions + races    → 대회 기본 정보
  2. race_weather             → 대회 당일 날씨
  3. race_courses             → 코스 고도 / 구간 데이터 (있을 때)
  4. RAG search               → 유사 날씨 × 기록 케이스
  5. Claude claude-opus-4-8 → 레이스 플랜 JSON 생성

[응답 스키마]
  race_name, goal_time, weather_summary, weather_assessment,
  strategy_overview, pace_plan[], attention_segments[],
  nutrition_plan{}, heart_rate_guide{}, rag_basis{}
"""

import json
import logging
from typing import Any

import anthropic
from app.core.config import settings
from app.core.database import review_db
from app.services import rag_service

logger = logging.getLogger(__name__)

MODEL = "claude-opus-4-8"
MAX_TOKENS = 4096

COURSE_LABELS = {"FULL": "풀마라톤 (42.195km)", "HALF": "하프마라톤 (21.0975km)", "10K": "10K (10km)"}

TRAINING_LABELS = {
    "best":   "최상 — 피크 훈련 완료, 몸 상태 최고",
    "good":   "좋음 — 꾸준히 훈련, 컨디션 양호",
    "normal": "보통 — 기본 훈련, 무리 없음",
    "poor":   "부족 — 훈련 불충분, 컨디션 우려",
}


# ── 데이터 수집 헬퍼 ──────────────────────────────────────────────────────────

def _fetch_race_info(race_edition_id: int, live: bool) -> dict[str, Any]:
    """race_editions + races 조인해 기본 정보 반환."""
    rows = review_db(live).table("race_editions") \
        .select("id, year, race_date, location, city, race_id, races(name, city, wa_label)") \
        .eq("id", race_edition_id) \
        .limit(1) \
        .execute().data
    if not rows:
        raise ValueError(f"race_edition_id={race_edition_id} 를 찾을 수 없습니다.")
    return rows[0]


def _fetch_weather(race_edition_id: int, live: bool) -> dict[str, Any] | None:
    """race_weather 에서 해당 에디션 날씨 조회."""
    rows = review_db(live).table("race_weather") \
        .select("temperature, humidity, wind_speed, wind_direction, weather_condition") \
        .eq("race_id", "race_id") \
        .limit(1) \
        .execute().data

    # race_weather는 race_id 기반 — edition의 race_id로 조회해야 함.
    # edition 정보는 호출자가 미리 가져오므로 별도 파라미터로 받음
    return rows[0] if rows else None


def _fetch_weather_by_race(race_id: int, live: bool) -> dict[str, Any] | None:
    rows = review_db(live).table("race_weather") \
        .select("temperature, humidity, wind_speed, wind_direction, weather_condition") \
        .eq("race_id", race_id) \
        .limit(1) \
        .execute().data
    return rows[0] if rows else None


def _fetch_course(race_edition_id: int, course_type: str, live: bool) -> dict[str, Any] | None:
    rows = review_db(live).table("race_courses") \
        .select("gpx_url, elevation_data, segments, source, is_certified") \
        .eq("race_edition_id", race_edition_id) \
        .eq("course_type", course_type) \
        .limit(1) \
        .execute().data
    return rows[0] if rows else None


# ── 컨텍스트 텍스트 빌더 ──────────────────────────────────────────────────────

def _weather_text(weather: dict | None) -> str:
    if not weather:
        return "날씨 데이터 없음 (평년 기준으로 판단)"
    parts = []
    if weather.get("temperature") is not None:
        parts.append(f"기온 {weather['temperature']}°C")
    if weather.get("humidity") is not None:
        parts.append(f"습도 {weather['humidity']}%")
    if weather.get("wind_speed") is not None:
        dir_map = {"N":"북","NE":"북동","E":"동","SE":"남동","S":"남","SW":"남서","W":"서","NW":"북서"}
        direction = dir_map.get(weather.get("wind_direction",""), weather.get("wind_direction",""))
        parts.append(f"바람 {direction}{weather['wind_speed']}m/s" if direction else f"바람 {weather['wind_speed']}m/s")
    if weather.get("weather_condition"):
        parts.append(weather["weather_condition"])
    return ", ".join(parts) if parts else "날씨 정보 불충분"


def _course_text(course: dict | None) -> str:
    if not course:
        return "공식 코스 데이터 없음 (일반적인 도심 마라톤 코스 기준으로 판단)"
    lines = []
    if course.get("is_certified"):
        lines.append("공인 코스")
    if course.get("elevation_data"):
        elev = course["elevation_data"]
        if isinstance(elev, dict):
            gain = elev.get("total_gain_m")
            max_elev = elev.get("max_m")
            if gain:
                lines.append(f"총 고도 상승 {gain}m")
            if max_elev:
                lines.append(f"최고 고도 {max_elev}m")
    if course.get("segments"):
        segs = course["segments"]
        if isinstance(segs, list) and segs:
            seg_desc = []
            for seg in segs[:6]:
                if isinstance(seg, dict):
                    km = seg.get("km_range", "")
                    char = seg.get("characteristic", "")
                    if km and char:
                        seg_desc.append(f"{km}km {char}")
            if seg_desc:
                lines.append("구간 특성: " + " / ".join(seg_desc))
    return " | ".join(lines) if lines else "코스 등록됨 (상세 데이터 없음)"


def _rag_cases_text(cases: list[dict]) -> str:
    if not cases:
        return "유사 케이스 없음 (첫 데이터 수집 중)"
    lines = []
    for i, c in enumerate(cases[:5], 1):
        secs = c.get("finish_time_seconds")
        if secs:
            h, rem = divmod(int(secs), 3600)
            m, s = divmod(rem, 60)
            time_str = f"{h}:{m:02d}:{s:02d}"
        else:
            time_str = "미기록"
        temp = c.get("temperature")
        sim  = c.get("similarity", 0)
        lines.append(
            f"  케이스{i}: 기온 {temp}°C, 완주기록 {time_str}, 유사도 {sim:.2f}"
        )
    return "\n".join(lines)


def _seconds_to_hms(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def _goal_pace(goal_seconds: int, course_type: str) -> str:
    dist = {"FULL": 42195, "HALF": 21097.5, "10K": 10000}.get(course_type, 42195)
    pace_sec_per_km = goal_seconds / (dist / 1000)
    m, s = divmod(int(pace_sec_per_km), 60)
    return f"{m}'{s:02d}\"/km"


# ── 프롬프트 빌더 ─────────────────────────────────────────────────────────────

def _build_prompt(
    race_info: dict,
    weather: dict | None,
    course: dict | None,
    rag_cases: list[dict],
    course_type: str,
    goal_time: str,
    recent_long_km: float | None,
    recent_10k_time: str | None,
    training_status: str,
) -> tuple[str, str]:
    """(system_prompt, user_prompt) 반환."""
    race = race_info.get("races") or {}
    race_name = race.get("name", "대회")
    year      = race_info.get("year", "")
    location  = race_info.get("location") or race_info.get("city") or race.get("city", "")
    wa_label  = race.get("wa_label", "")
    course_label = COURSE_LABELS.get(course_type, course_type)

    # 목표기록 초 변환
    try:
        h, m, s = [int(x) for x in goal_time.split(":")]
        goal_sec = h * 3600 + m * 60 + s
    except Exception:
        goal_sec = 0

    system = f"""당신은 마라톤 전문 코치입니다.
선수의 목표 기록, 훈련 상태, 대회 날씨, 코스 특성, 그리고 실제 완주자 데이터를 바탕으로
구체적이고 실행 가능한 레이스 플랜을 한국어로 작성합니다.

반드시 아래 JSON 형식으로만 응답하세요. JSON 외 다른 텍스트를 추가하지 마세요.

{{
  "race_name": "대회명 (연도 포함)",
  "goal_time": "HH:MM:SS",
  "weather_summary": "한 줄 날씨 요약",
  "weather_assessment": "날씨가 레이스에 미치는 영향 (1~2문장)",
  "strategy_overview": "전체 레이스 전략 요약 (3~4문장)",
  "pace_plan": [
    {{
      "segment": "0-10km",
      "target_pace": "X'XX\"/km",
      "cumulative_time": "HH:MM:SS",
      "note": "구간 전략 (1문장)"
    }}
  ],
  "attention_segments": [
    {{
      "segment": "30-33km",
      "reason": "주의 이유",
      "tip": "대처 방법"
    }}
  ],
  "nutrition_plan": {{
    "hydration": "수분 섭취 전략",
    "gel_timing": ["Xkm", "Ykm"],
    "advice": "영양 전략 요약"
  }},
  "heart_rate_guide": {{
    "early_phase_bpm": "X-Y bpm",
    "mid_phase_bpm": "X-Y bpm",
    "late_phase_bpm": "최대 Z bpm",
    "advice": "심박 관리 조언"
  }},
  "rag_basis": {{
    "cases_found": 0,
    "summary": "유사 케이스 기반 인사이트"
  }}
}}"""

    user = f"""## 대회 정보
- 대회명: {race_name} {year}
- 코스: {course_label}
- 장소: {location}
{f'- 세계육상연맹 인증: {wa_label}' if wa_label else ''}

## 날씨 조건
{_weather_text(weather)}

## 코스 특성
{_course_text(course)}

## 러너 프로필
- 목표 완주기록: {goal_time} (평균 페이스: {_goal_pace(goal_sec, course_type) if goal_sec else '미계산'})
- 훈련 상태: {TRAINING_LABELS.get(training_status, training_status)}
{f'- 최근 최장 거리 훈련: {recent_long_km}km' if recent_long_km else ''}
{f'- 최근 10km 기록: {recent_10k_time}' if recent_10k_time else ''}

## 유사 조건 완주자 데이터 (RAG)
{_rag_cases_text(rag_cases)}
케이스 수: {len(rag_cases)}건

위 정보를 종합해 {race_name} {year} {course_label} 레이스 플랜을 JSON으로 작성하세요.
pace_plan은 5km 단위 구간으로 구성하되, 코스 특성상 중요 변곡점이 있다면 세분화하세요."""

    return system, user


# ── 메인 생성 함수 ────────────────────────────────────────────────────────────

def generate(
    race_edition_id: int,
    course_type: str,
    goal_time: str,
    training_status: str = "normal",
    recent_long_km: float | None = None,
    recent_10k_time: str | None = None,
    live: bool = True,
) -> dict[str, Any]:
    """
    레이스 플랜 생성.

    1. DB에서 대회·날씨·코스 정보 수집
    2. RAG로 유사 케이스 검색
    3. Claude claude-opus-4-8 에 프롬프트 전달
    4. JSON 응답 파싱 후 반환
    """
    logger.info(f"[RacePlan] 생성 시작 edition={race_edition_id} type={course_type} goal={goal_time}")

    # 1. 대회 정보
    race_info = _fetch_race_info(race_edition_id, live)
    race_id   = race_info.get("race_id")

    # 2. 날씨
    weather = _fetch_weather_by_race(race_id, live) if race_id else None

    # 3. 코스
    course = _fetch_course(race_edition_id, course_type, live)

    # 4. RAG 유사 케이스
    rag_cases: list[dict] = []
    try:
        race  = race_info.get("races") or {}
        query_text = rag_service.build_case_text(
            race_name=race.get("name", "마라톤"),
            year=race_info.get("year"),
            course_type=course_type,
            temperature=weather.get("temperature") if weather else None,
            humidity=weather.get("humidity") if weather else None,
            wind_speed=weather.get("wind_speed") if weather else None,
            finish_time_seconds=None,
        )
        embedding = rag_service.generate_embedding(query_text)
        rag_cases = rag_service.search_similar(embedding, match_threshold=0.4, match_count=5, live=live)
    except Exception as e:
        logger.warning(f"[RacePlan] RAG 검색 실패 (무시): {e}")

    # 5. 프롬프트 구성
    system_prompt, user_prompt = _build_prompt(
        race_info=race_info,
        weather=weather,
        course=course,
        rag_cases=rag_cases,
        course_type=course_type,
        goal_time=goal_time,
        recent_long_km=recent_long_km,
        recent_10k_time=recent_10k_time,
        training_status=training_status,
    )

    # 6. Claude 호출
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = ""
    for block in response.content:
        if block.type == "text":
            raw_text = block.text
            break

    # 7. JSON 파싱
    try:
        # Claude가 ```json ... ``` 래핑을 붙이는 경우 제거
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
        if text.endswith("```"):
            text = text[: text.rfind("```")]
        plan = json.loads(text.strip())
    except json.JSONDecodeError as e:
        logger.error(f"[RacePlan] JSON 파싱 실패: {e}\n응답: {raw_text[:500]}")
        raise ValueError(f"레이스 플랜 파싱 실패: {e}")

    # 8. 메타데이터 추가
    plan["_meta"] = {
        "race_edition_id": race_edition_id,
        "course_type":      course_type,
        "goal_time":        goal_time,
        "training_status":  training_status,
        "rag_cases_found":  len(rag_cases),
        "has_weather":      weather is not None,
        "has_course":       course is not None,
        "model":            MODEL,
    }

    logger.info(f"[RacePlan] 생성 완료 edition={race_edition_id}")
    return plan
