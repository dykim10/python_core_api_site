"""
포토 갤러리 이미지 처리 라우터 (app/api/routes/photo.py)

CREW(Laravel) 관리자가 포토 갤러리에 이미지를 업로드할 때 호출.
Pillow로 리사이즈 + WebP 변환 후 S3에 저장하고 URL을 반환한다.

엔드포인트:
  POST /api/photo/resize-webp
    - 원본 이미지 → max 800×800 비율 유지 리사이즈 → WebP 변환 → S3 저장
    - 저장 경로: {folder}/{uuid}_thumb.webp  (folder 기본값: photo-galleries/{YYYY}/{MM})
    - 응답: { "thumbnail_url": str, "width": int, "height": int }
    - folder 파라미터로 S3 저장 경로 prefix 지정 가능 (예: avatars/42)
"""
import io
import uuid
import boto3
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from typing import Optional
try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

from app.core.config import settings

router = APIRouter(prefix="/api/photo", tags=["photo"])

SUPPORTED_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}
MAX_SIZE_BYTES  = 10 * 1024 * 1024   # 10MB
THUMBNAIL_MAX   = (800, 800)          # 장축 최대 800px
WEBP_QUALITY    = 85


class ResizeWebpResponse(BaseModel):
    thumbnail_url: str
    width: int
    height: int


def _convert_to_webp(image_bytes: bytes) -> tuple[bytes, int, int]:
    """Pillow로 리사이즈 + WebP 변환. (webp_bytes, width, height) 반환."""
    with Image.open(io.BytesIO(image_bytes)) as img:
        # RGBA / P(팔레트) 모드 → RGB 변환 (WebP는 RGBA 지원하나 일관성 유지)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")

        # 비율 유지 리사이즈 (THUMBNAIL_MAX 초과할 때만)
        img.thumbnail(THUMBNAIL_MAX, Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=WEBP_QUALITY, method=6)
        return buf.getvalue(), img.width, img.height


def _upload_webp(webp_bytes: bytes, folder: str) -> str:
    """변환된 WebP 바이트를 S3에 저장하고 URL을 반환한다."""
    key = f"{folder.strip('/')}/{uuid.uuid4().hex}.webp"

    s3 = boto3.client(
        "s3",
        region_name=settings.aws_default_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    s3.put_object(
        Bucket=settings.aws_bucket,
        Key=key,
        Body=webp_bytes,
        ContentType="image/webp",
    )
    return f"https://{settings.aws_bucket}.s3.{settings.aws_default_region}.amazonaws.com/{key}"


@router.post("/resize-webp", response_model=ResizeWebpResponse)
async def resize_to_webp(
    file: UploadFile = File(..., description="변환할 원본 이미지"),
    folder: Optional[str] = Form(None, description="S3 저장 경로 prefix (기본: photo-galleries/YYYY/MM)"),
):
    """이미지 리사이즈 + WebP 변환 → S3 저장 → thumbnail_url 반환"""
    if not _PIL_AVAILABLE:
        raise HTTPException(status_code=503, detail="Pillow 미설치 — pip install Pillow 후 재시작하세요.")

    if file.content_type not in SUPPORTED_TYPES:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 형식: {file.content_type}")

    image_bytes = await file.read()
    if len(image_bytes) > MAX_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="이미지 크기는 10MB 이하여야 합니다.")

    # folder 미지정 시 기본 경로 사용
    if not folder:
        now    = datetime.now()
        folder = f"photo-galleries/{now.year}/{now.month:02d}"

    try:
        webp_bytes, width, height = _convert_to_webp(image_bytes)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"이미지 변환 실패: {str(e)}")

    try:
        thumbnail_url = _upload_webp(webp_bytes, folder)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"S3 업로드 실패: {str(e)}")

    return ResizeWebpResponse(thumbnail_url=thumbnail_url, width=width, height=height)
