"""
러닝 이미지 파싱 라우터 (app/api/routes/parse_image.py)

CREW(Laravel) 에서 호출하는 핵심 엔드포인트.
러닝 앱 스크린샷을 S3 에 저장하고, Claude Vision 으로 수치를 추출해 반환한다.

POST /api/parse-image
  요청  : multipart/form-data — file (이미지, 최대 10MB)
  지원  : JPEG / PNG / GIF / WebP
  응답  : {
    "s3_url"           : S3 저장 URL,
    "run_date"         : "YYYY-MM-DD",
    "distance_km"      : 거리(float),
    "duration_seconds" : 총 시간(int, 초),
    "avg_pace_seconds" : 평균 페이스(int, 초/km),
    "best_pace_seconds": 최고 페이스(int, 초/km),
    "calories"         : 소모 칼로리(int),
    "avg_heart_rate"   : 평균 심박수(int, bpm),
    "is_indoor"        : 실내 여부(bool),
    "elevation_m"      : 누적 고도(float),
    "raw_parsed"       : Claude 원본 응답 dict
  }

[처리 흐름]
  1. 파일 타입 · 크기(10MB) 검증
  2. _upload_to_s3 — running-logs/{uuid}.{ext} 경로로 S3 저장
  3. invoke_with_image — _build_parse_prompt() 로 Claude Vision 파싱
  4. JSON 파싱 (```json 마크다운 블록 제거 후 json.loads)
  5. _normalize_run_date — 연도 보정

[_normalize_run_date 연도 보정 로직]
  - year_in_image=True  (이미지에 연도가 명시된 경우):
      연도를 그대로 신뢰. 미래 날짜인 경우에만 전년도로 교정.
  - year_in_image=False (이미지에 연도가 없어 Claude가 당해년도를 사용한 경우):
      너무 오래된 연도(2년 이상 과거)면 당해년도로 교정. 미래 날짜 교정도 적용.

[앱별 날짜 표시 패턴]
  COROS  : 항상 연도 표시 (예: '2026/06/07', '2026년 6월 7일')
  Garmin : 당해연도 기록은 연도 생략 (예: '6월 3일'), 과거 기록은 연도 표시 (예: '2024년 9월 22일')
"""
import json
import re
import uuid
import boto3
from datetime import date as date_type, datetime
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.services.claude_client import invoke_with_image
from app.core.config import settings

router = APIRouter(prefix="/api", tags=["image"])

SUPPORTED_TYPES = {
    "image/jpeg": "image/jpeg",
    "image/jpg":  "image/jpeg",
    "image/png":  "image/png",
    "image/gif":  "image/gif",
    "image/webp": "image/webp",
}

# {today_str}, {current_year} 은 _build_parse_prompt() 에서 주입
# {{ }} 는 str.format() 이스케이프 → 실제 { } 로 출력됨
PARSE_PROMPT_TEMPLATE = """\
이 이미지는 러닝 앱(Nike Run Club, Strava, Garmin, COROS, 애플워치 등)의 운동 기록 화면입니다.
이미지에서 아래 항목을 추출하여 JSON 형식으로만 응답해주세요. 없는 항목은 null로 표기하세요.

오늘 날짜: {today_str} (현재 연도: {current_year}년)

{{
  "app_name": 문자열,
  "activity_type": 문자열,
  "run_date": "YYYY-MM-DD",
  "year_in_image": true/false,
  "distance_km": 숫자 (킬로미터, 소수점 2자리),
  "duration_seconds": 숫자 (총 운동시간, 초 단위 정수),
  "avg_pace_seconds": 숫자 (평균 페이스, 초/km 정수. 예: 5분30초 → 330),
  "best_pace_seconds": 숫자 (최고 페이스, 초/km 정수),
  "calories": 숫자 (정수),
  "avg_heart_rate": 숫자 (정수, bpm),
  "is_indoor": true/false (트레드밀/실내이면 true, 실외면 false),
  "elevation_m": 숫자 (누적 고도, 미터),
  "has_map": true/false (지도 포함 여부),
  "vo2max": 숫자 (시계/앱에 VO2max 표시 시, 소수 1자리. 없으면 null)
}}

[app_name 규칙] 앱 로고·UI 레이아웃으로 판별. 아래 값 중 하나:
  "coros"          → COROS 앱 (빨간 육각형 기어 로고, 상단에 YYYY/MM/DD 날짜)
  "garmin"         → Garmin Connect (러너 실루엣 원형 아이콘, 개요/통계/랩/차트 탭)
  "apple_watch"    → Apple Watch / Apple Fitness (링 형태 활동 UI, iOS 스타일)
  "samsung_health" → Samsung Health (삼성헬스, 갤럭시 워치 연동)
  "nike_run_club"  → Nike Run Club (NRC, 나이키 로고)
  "strava"         → Strava (주황색 S 로고)
  "polar"          → Polar Flow (Polar 로고, 핀란드 브랜드)
  "suunto"         → Suunto (핀란드 브랜드, 독특한 지도 색상)
  "amazfit"        → Amazfit / Zepp (화미, Zepp 로고)
  "huawei_health"  → Huawei Health / 화웨이 헬스
  "adidas_running" → Adidas Running / Runtastic
  "xiaomi_fitness" → Xiaomi Mi Fitness / 샤오미
  "wahoo"          → Wahoo (자전거·트라이애슬론 전용)
  "unknown"        → 판별 불가

[activity_type 규칙] 활동 유형 레이블·지도·수치 패턴으로 판별. 아래 값 중 하나:
  "running"       → 일반 러닝 (예: '러닝', 'Running', 'Road Run')
  "trail_running" → 트레일 러닝 (예: '트레일 러닝', 'Trail Run', 고도 상승 큰 경우)
  "treadmill"     → 트레드밀 실내 러닝 (지도 없음 + 실내 레이블 또는 '러닝머신', 'Treadmill')
  "walking"       → 걷기 (예: '걷기', 'Walking', 페이스 8분/km 이상)
  "cycling"       → 자전거 (예: '사이클링', 'Cycling', 'Ride')
  "unknown"       → 판별 불가
  ※ is_indoor: activity_type이 "treadmill"이면 반드시 true

[run_date 추출 규칙]
- 연도(4자리)가 이미지에 명시된 경우: 그 연도를 그대로 사용하고 year_in_image를 true로 설정
  예) '2024년 9월 22일' → "2024-09-22", year_in_image: true
  예) '2026/06/07' → "2026-06-07", year_in_image: true
- 연도 없이 월/일만 있는 경우: 현재 연도({current_year})를 사용하고 year_in_image를 false로 설정
  예) '6월 3일' → "{current_year}-06-03", year_in_image: false
- 날짜 정보가 전혀 없으면: null

JSON 외에 다른 텍스트는 절대 포함하지 마세요.\
"""


class ParseImageResponse(BaseModel):
    s3_url: str
    app_name: Optional[str] = None
    activity_type: Optional[str] = None
    run_date: Optional[str] = None
    distance_km: Optional[float] = None
    duration_seconds: Optional[int] = None
    avg_pace_seconds: Optional[int] = None
    best_pace_seconds: Optional[int] = None
    calories: Optional[int] = None
    avg_heart_rate: Optional[int] = None
    is_indoor: bool = False
    elevation_m: Optional[float] = None
    has_map: Optional[bool] = None
    vo2max: Optional[float] = None
    raw_parsed: dict = {}


def _build_parse_prompt() -> str:
    today = date_type.today()
    return PARSE_PROMPT_TEMPLATE.format(
        today_str=today.strftime('%Y년 %m월 %d일'),
        current_year=today.year,
    )


def _normalize_run_date(raw: str | None, year_in_image: bool = True) -> str | None:
    if not raw:
        return None
    raw = str(raw).strip()
    today = date_type.today()
    current_year = today.year

    # 4자리 연도가 없으면 당해년도 붙임 (Claude가 연도 없이 반환한 경우)
    if not re.search(r'\b\d{4}\b', raw):
        raw = f"{current_year}-{raw}"

    parsed_date = None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            parsed_date = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue

    if parsed_date is None:
        return None

    # 이미지에 연도가 없는 경우에만 "너무 오래된 연도" 교정 적용
    # 이미지에 연도가 있으면 과거 기록도 그대로 신뢰 (예: 2024년 9월 22일 실제 기록)
    if not year_in_image and parsed_date.year < current_year - 1:
        parsed_date = parsed_date.replace(year=current_year)

    # 미래 날짜이면 전년도로 교정 (최후 안전망)
    if parsed_date.date() > today:
        parsed_date = parsed_date.replace(year=current_year - 1)

    return parsed_date.strftime("%Y-%m-%d")


def _upload_to_s3(image_bytes: bytes, content_type: str) -> str:
    ext = content_type.split("/")[-1].replace("jpeg", "jpg")
    key = f"running-logs/{uuid.uuid4().hex}.{ext}"

    s3 = boto3.client(
        "s3",
        region_name=settings.aws_default_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    s3.put_object(
        Bucket=settings.aws_bucket,
        Key=key,
        Body=image_bytes,
        ContentType=content_type,
    )
    base = settings.aws_url.rstrip('/') if settings.aws_url else \
           f"https://{settings.aws_bucket}.s3.{settings.aws_default_region}.amazonaws.com"
    return f"{base}/{key}"


def _parse_image_bytes(image_bytes: bytes, media_type: str) -> dict:
    """Claude Vision 파싱 — S3 업로드 없음."""
    prompt = _build_parse_prompt()
    raw = invoke_with_image(image_bytes, media_type, prompt)
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = json.loads(cleaned)

    year_in_image = bool(parsed.get("year_in_image", True))
    activity_type = parsed.get("activity_type") or "unknown"
    is_indoor = bool(parsed.get("is_indoor") or False)
    if activity_type == "treadmill":
        is_indoor = True

    return {
        "app_name": parsed.get("app_name") or "unknown",
        "activity_type": activity_type,
        "run_date": _normalize_run_date(parsed.get("run_date"), year_in_image),
        "distance_km": parsed.get("distance_km"),
        "duration_seconds": parsed.get("duration_seconds"),
        "avg_pace_seconds": parsed.get("avg_pace_seconds"),
        "best_pace_seconds": parsed.get("best_pace_seconds"),
        "calories": parsed.get("calories"),
        "avg_heart_rate": parsed.get("avg_heart_rate"),
        "is_indoor": is_indoor,
        "elevation_m": parsed.get("elevation_m"),
        "has_map": parsed.get("has_map"),
        "vo2max": parsed.get("vo2max"),
        "raw_parsed": parsed,
    }


class ParseImageEphemeralResponse(BaseModel):
    """S3 저장 없이 1회성 파싱 결과 (레이스 플랜 보조 입력용)."""
    app_name: Optional[str] = None
    activity_type: Optional[str] = None
    run_date: Optional[str] = None
    distance_km: Optional[float] = None
    duration_seconds: Optional[int] = None
    avg_pace_seconds: Optional[int] = None
    best_pace_seconds: Optional[int] = None
    calories: Optional[int] = None
    avg_heart_rate: Optional[int] = None
    is_indoor: bool = False
    elevation_m: Optional[float] = None
    has_map: Optional[bool] = None
    vo2max: Optional[float] = None
    raw_parsed: dict = {}


async def _read_image_upload(file: UploadFile) -> tuple[bytes, str]:
    media_type = SUPPORTED_TYPES.get(file.content_type or "")
    if not media_type:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 이미지 형식: {file.content_type}")

    image_bytes = await file.read()
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="이미지 크기는 10MB 이하여야 합니다.")
    if len(image_bytes) == 0:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")

    return image_bytes, media_type


@router.post("/parse-image/ephemeral", response_model=ParseImageEphemeralResponse)
async def parse_image_ephemeral(file: UploadFile = File(...)):
    """
    러닝 앱 스크린샷 1회성 파싱 — S3 저장 없음.
    REVIEW 레이스 플랜 생성 시 보조 훈련 데이터 추출용.
    """
    image_bytes, media_type = await _read_image_upload(file)
    try:
        parsed = _parse_image_bytes(image_bytes, media_type)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"AI 응답 파싱 실패: {e}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 파싱 오류: {e}") from e

    return ParseImageEphemeralResponse(**parsed)


@router.post("/parse-image", response_model=ParseImageResponse)
async def parse_image(file: UploadFile = File(...)):
    image_bytes, media_type = await _read_image_upload(file)

    # 1. S3 업로드
    try:
        s3_url = _upload_to_s3(image_bytes, media_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"S3 업로드 실패: {str(e)}")

    # 2. Claude Vision 파싱
    try:
        parsed = _parse_image_bytes(image_bytes, media_type)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="AI 응답 파싱 실패")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 파싱 오류: {str(e)}")

    return ParseImageResponse(
        s3_url=s3_url,
        **parsed,
    )
