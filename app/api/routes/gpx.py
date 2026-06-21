"""
GPX 코스 파일 S3 업로드/삭제 라우터 (app/api/routes/gpx.py)

REVIEW 관리자가 공식 GPX 코스 파일을 업로드할 때 호출.
검증 후 S3에 고정 경로로 저장하고, 업로드 시점에 딱 한 번 고도/구간 데이터를
파싱해 함께 반환한다 (race_plan_service.py는 이 결과만 읽으므로 사용자별
반복 다운로드/파싱이 없다 — gpx_service.py 모듈 docstring 참고).

엔드포인트:
  POST /api/gpx/upload
    - multipart: file (GPX), race_edition_id (int), course_type (FULL/HALF/10K)
    - S3 저장 경로: race-courses/{race_edition_id}/{course_type}.gpx
    - 응답: { "gpx_url": str, "elevation_data": dict|null, "segments": list|null,
               "coordinates": list|null, "markers": list|null }

  DELETE /api/gpx/delete
    - query: url (S3 or CloudFront URL)
    - S3 오브젝트 삭제
"""
import boto3
from urllib.parse import urlparse
from typing import Any, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query
from pydantic import BaseModel
from app.core.config import settings
from app.services.gpx_service import parse_gpx_bytes

router = APIRouter(prefix="/api/gpx", tags=["gpx"])

ALLOWED_CONTENT_TYPES = {
    "application/gpx+xml",
    "application/xml",
    "text/xml",
    "application/octet-stream",
}
ALLOWED_EXTENSIONS = {".gpx", ".xml"}
MAX_SIZE_BYTES = 20 * 1024 * 1024   # 20MB
VALID_COURSE_TYPES = {"FULL", "HALF", "10K"}


class GpxUploadResponse(BaseModel):
    gpx_url: str
    elevation_data: Optional[dict[str, Any]] = None
    segments: Optional[list[dict[str, Any]]] = None
    coordinates: Optional[list[dict[str, float]]] = None
    markers: Optional[list[dict[str, Any]]] = None


def _s3_client():
    return boto3.client(
        "s3",
        region_name=settings.aws_default_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


@router.post("/upload", response_model=GpxUploadResponse)
async def upload_gpx(
    file: UploadFile = File(..., description="GPX 코스 파일 (.gpx / .xml)"),
    race_edition_id: int = Form(..., description="race_editions.id"),
    course_type: str = Form(..., description="FULL / HALF / 10K"),
):
    """공식 GPX 코스 파일을 S3에 업로드하고 URL을 반환한다."""
    course_type = course_type.upper()
    if course_type not in VALID_COURSE_TYPES:
        raise HTTPException(status_code=400, detail=f"course_type은 {VALID_COURSE_TYPES} 중 하나여야 합니다.")

    filename = file.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="GPX(.gpx) 또는 XML(.xml) 파일만 업로드 가능합니다.")

    gpx_bytes = await file.read()
    if len(gpx_bytes) > MAX_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="파일 크기는 20MB 이하여야 합니다.")
    if not gpx_bytes:
        raise HTTPException(status_code=400, detail="빈 파일은 업로드할 수 없습니다.")

    key = f"race-courses/{race_edition_id}/{course_type}.gpx"

    try:
        s3 = _s3_client()
        s3.put_object(
            Bucket=settings.aws_bucket,
            Key=key,
            Body=gpx_bytes,
            ContentType="application/gpx+xml",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"S3 업로드 실패: {str(e)}")

    base = settings.aws_url.rstrip("/") if settings.aws_url else \
           f"https://{settings.aws_bucket}.s3.{settings.aws_default_region}.amazonaws.com"

    parsed = parse_gpx_bytes(gpx_bytes)

    return GpxUploadResponse(
        gpx_url=f"{base}/{key}",
        elevation_data=parsed["elevation_data"] if parsed else None,
        segments=parsed["segments"] if parsed else None,
        coordinates=parsed["coordinates"] if parsed else None,
        markers=parsed["markers"] if parsed else None,
    )


@router.delete("/delete")
async def delete_gpx(url: str = Query(..., description="삭제할 GPX 파일의 S3 또는 CDN URL")):
    """S3 GPX 파일 삭제 — URL에서 오브젝트 키 자동 추출"""
    key = urlparse(url).path.lstrip("/")
    if not key:
        raise HTTPException(status_code=400, detail="유효하지 않은 URL입니다.")

    try:
        _s3_client().delete_object(Bucket=settings.aws_bucket, Key=key)
        return {"deleted": key}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"S3 삭제 실패: {str(e)}")
