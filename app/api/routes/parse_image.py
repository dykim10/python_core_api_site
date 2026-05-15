import json
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import Optional
from decimal import Decimal

from app.services.claude_client import invoke_with_image

router = APIRouter(prefix="/api", tags=["image"])

SUPPORTED_TYPES = {
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/png": "image/png",
    "image/gif": "image/gif",
    "image/webp": "image/webp",
}

PARSE_PROMPT = """이 이미지는 러닝 앱(Nike Run Club, Strava, 가민, 애플워치 등)의 운동 기록 화면입니다.
이미지에서 아래 항목을 추출하여 JSON 형식으로만 응답해주세요. 없는 항목은 null로 표기하세요.

{
  "distance_km": 숫자 (킬로미터, 소수점 2자리),
  "avg_pace": "문자열 (예: 5'30\"/km)",
  "best_pace": "문자열 (예: 4'50\"/km)",
  "duration_sec": 숫자 (총 운동시간, 초 단위),
  "calories": 숫자 (정수),
  "avg_heart_rate": 숫자 (정수, bpm),
  "is_indoor": true/false (트레드밀이면 true, 실외면 false),
  "altitude_m": 숫자 (누적 고도, 미터),
  "has_map": true/false (지도 포함 여부)
}

JSON 외에 다른 텍스트는 절대 포함하지 마세요."""


class ParseImageResponse(BaseModel):
    distance_km: Optional[Decimal] = None
    avg_pace: Optional[str] = None
    best_pace: Optional[str] = None
    duration_sec: Optional[int] = None
    calories: Optional[int] = None
    avg_heart_rate: Optional[int] = None
    is_indoor: bool = False
    altitude_m: Optional[Decimal] = None
    has_map: bool = False


@router.post("/parse-image", response_model=ParseImageResponse)
async def parse_image(file: UploadFile = File(...)):
    media_type = SUPPORTED_TYPES.get(file.content_type)
    if not media_type:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 이미지 형식입니다: {file.content_type}")

    image_bytes = await file.read()
    if len(image_bytes) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="이미지 크기는 5MB 이하여야 합니다.")

    try:
        raw = invoke_with_image(image_bytes, media_type, PARSE_PROMPT)
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(cleaned)
        return ParseImageResponse(**data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"AI 응답 파싱 실패: {raw}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
