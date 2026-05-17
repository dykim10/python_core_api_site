import json
import uuid
import boto3
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

PARSE_PROMPT = """이 이미지는 러닝 앱(Nike Run Club, Strava, 가민, 애플워치 등)의 운동 기록 화면입니다.
이미지에서 아래 항목을 추출하여 JSON 형식으로만 응답해주세요. 없는 항목은 null로 표기하세요.

{
  "distance_km": 숫자 (킬로미터, 소수점 2자리),
  "duration_seconds": 숫자 (총 운동시간, 초 단위 정수),
  "avg_pace_seconds": 숫자 (평균 페이스, 초/km 정수. 예: 5분30초 → 330),
  "best_pace_seconds": 숫자 (최고 페이스, 초/km 정수),
  "calories": 숫자 (정수),
  "avg_heart_rate": 숫자 (정수, bpm),
  "is_indoor": true/false (트레드밀이면 true, 실외면 false),
  "elevation_m": 숫자 (누적 고도, 미터),
  "has_map": true/false (지도 포함 여부)
}

JSON 외에 다른 텍스트는 절대 포함하지 마세요."""


class ParseImageResponse(BaseModel):
    s3_url: str
    distance_km: Optional[float] = None
    duration_seconds: Optional[int] = None
    avg_pace_seconds: Optional[int] = None
    best_pace_seconds: Optional[int] = None
    calories: Optional[int] = None
    avg_heart_rate: Optional[int] = None
    is_indoor: bool = False
    elevation_m: Optional[float] = None
    has_map: Optional[bool] = None
    raw_parsed: dict = {}


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
    return f"https://{settings.aws_bucket}.s3.{settings.aws_default_region}.amazonaws.com/{key}"


@router.post("/parse-image", response_model=ParseImageResponse)
async def parse_image(file: UploadFile = File(...)):
    media_type = SUPPORTED_TYPES.get(file.content_type)
    if not media_type:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 이미지 형식: {file.content_type}")

    image_bytes = await file.read()
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="이미지 크기는 10MB 이하여야 합니다.")

    # 1. S3 업로드
    try:
        s3_url = _upload_to_s3(image_bytes, media_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"S3 업로드 실패: {str(e)}")

    # 2. GPT-4o Vision 파싱
    try:
        raw = invoke_with_image(image_bytes, media_type, PARSE_PROMPT)
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"AI 응답 파싱 실패: {raw}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 파싱 오류: {str(e)}")

    return ParseImageResponse(
        s3_url=s3_url,
        distance_km=parsed.get("distance_km"),
        duration_seconds=parsed.get("duration_seconds"),
        avg_pace_seconds=parsed.get("avg_pace_seconds"),
        best_pace_seconds=parsed.get("best_pace_seconds"),
        calories=parsed.get("calories"),
        avg_heart_rate=parsed.get("avg_heart_rate"),
        is_indoor=parsed.get("is_indoor", False),
        elevation_m=parsed.get("elevation_m"),
        has_map=parsed.get("has_map"),
        raw_parsed=parsed,
    )
