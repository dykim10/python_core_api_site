"""
PB(개인기록) 이미지 파싱 — 1회성, 이미지 저장 없음.

러닝 앱 기록·대회 결과 캡처 → distance_type / record_time / achieved_at 추출.
"""
import json
import logging
import re
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException, UploadFile

from app.services.body_service import read_image_upload
from app.services.claude_client import invoke_with_image

logger = logging.getLogger(__name__)

VALID_DISTANCES = frozenset({"1K", "5K", "10K", "HALF", "FULL"})

PB_PROMPT = """\
이 이미지는 러닝 PB(개인기록) 또는 대회·훈련 기록 화면입니다 (앱 캡처, 결과지, 메달 사진 등).
아래 항목을 JSON 형식으로만 응답하세요. 없는 항목은 null.

{
  "distance_type": "1K" | "5K" | "10K" | "HALF" | "FULL" | null,
  "distance_km": 숫자 또는 null,
  "record_time": "MM:SS" 또는 "H:MM:SS" 형식 문자열,
  "duration_seconds": 정수(초) 또는 null,
  "achieved_at": "YYYY-MM-DD",
  "year_in_image": true/false
}

distance_type 규칙:
- 1km 내외 → 1K, 5km → 5K, 10km → 10K
- 하프마라톤·21km → HALF, 풀·42km·마라톤 → FULL

record_time과 duration_seconds 중 하나 이상 반드시 추출. 둘 다 있으면 record_time 우선.

[절대 추출 금지] 이름, 전화번호, 이메일, 주민번호 등 개인 식별 정보
JSON 외 텍스트 금지. 마크다운 백틱 금지.\
"""


def _parse_claude_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    text = text.strip().removesuffix("```").strip()
    return json.loads(text)


def _normalize_achieved_at(raw: str | None, year_in_image: bool = True) -> str | None:
    if not raw:
        return None
    raw = str(raw).strip()
    today = date.today()
    current_year = today.year

    if not re.search(r"\b\d{4}\b", raw):
        raw = f"{current_year}-{raw}"

    parsed = None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            parsed = datetime.strptime(raw[:10], fmt)
            break
        except ValueError:
            continue

    if parsed is None:
        return None

    if not year_in_image and parsed.year < current_year - 1:
        parsed = parsed.replace(year=current_year)
    if parsed.date() > today:
        parsed = parsed.replace(year=current_year - 1)

    return parsed.strftime("%Y-%m-%d")


def _normalize_distance_type(raw: str | None, distance_km: float | None) -> str | None:
    if raw:
        key = str(raw).upper().strip().replace(" ", "").replace("-", "")
        aliases = {
            "1K": "1K", "1KM": "1K",
            "5K": "5K", "5KM": "5K",
            "10K": "10K", "10KM": "10K",
            "HALF": "HALF", "HALFMARATHON": "HALF", "21K": "HALF", "21KM": "HALF",
            "HM": "HALF",
            "FULL": "FULL", "MARATHON": "FULL", "42K": "FULL", "42KM": "FULL", "FM": "FULL",
        }
        if key in aliases:
            return aliases[key]
        if key in VALID_DISTANCES:
            return key

    if distance_km is not None:
        km = float(distance_km)
        if km < 2:
            return "1K"
        if km < 7:
            return "5K"
        if km < 15:
            return "10K"
        if km < 30:
            return "HALF"
        return "FULL"

    return None


def _parse_record_time_string(text: str) -> str | None:
    """MM:SS 또는 H:MM:SS 검증·정규화."""
    text = text.strip()
    parts = text.split(":")
    try:
        if len(parts) == 2:
            m, s = int(parts[0]), int(parts[1])
            if m < 0 or s < 0 or s >= 60:
                return None
            return f"{m}:{s:02d}"
        if len(parts) == 3:
            h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
            if h < 0 or m < 0 or s < 0 or m >= 60 or s >= 60:
                return None
            return f"{h}:{m:02d}:{s:02d}"
    except ValueError:
        return None
    return None


def _seconds_to_record_time(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    s = max(0, int(seconds))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def parse_pb_image(image_bytes: bytes, media_type: str) -> dict[str, Any]:
    """Claude Vision PB 파싱 — 이미지 저장 없음."""
    raw = invoke_with_image(image_bytes, media_type, PB_PROMPT, task="coach_pb_parse")
    try:
        parsed = _parse_claude_json(raw)
    except json.JSONDecodeError as e:
        logger.error("[PB] JSON 파싱 실패")
        raise HTTPException(status_code=502, detail="PB 이미지 파싱 결과를 해석할 수 없습니다.") from e

    year_in_image = bool(parsed.get("year_in_image", True))
    distance_km = parsed.get("distance_km")
    if distance_km is not None:
        try:
            distance_km = float(distance_km)
        except (TypeError, ValueError):
            distance_km = None

    distance_type = _normalize_distance_type(parsed.get("distance_type"), distance_km)

    record_time = parsed.get("record_time")
    if record_time:
        record_time = _parse_record_time_string(str(record_time))
    if not record_time and parsed.get("duration_seconds") is not None:
        try:
            record_time = _seconds_to_record_time(int(parsed["duration_seconds"]))
        except (TypeError, ValueError):
            pass

    achieved_at = _normalize_achieved_at(parsed.get("achieved_at"), year_in_image)

    if not distance_type and not record_time:
        raise HTTPException(
            status_code=422,
            detail="이미지에서 PB 거리·기록을 찾지 못했습니다. 직접 입력해 주세요.",
        )

    return {
        "distance_type": distance_type,
        "record_time": record_time,
        "achieved_at": achieved_at,
        "ephemeral": True,
    }


async def parse_pb_upload(file: UploadFile) -> dict[str, Any]:
    """업로드 파일 → PB 필드 (저장 없음)."""
    image_bytes, media_type = await read_image_upload(file)
    result = parse_pb_image(image_bytes, media_type)
    logger.info("[PB] 이미지 파싱 완료 (저장 없음)")
    return result
