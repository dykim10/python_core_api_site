"""
공식 코스 고저도 프로파일 API.

POST /api/course/elevation — S3 GPX → elevation_data JSON (REVIEW race_courses 저장용)
"""
import boto3
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.course_elevation_service import build_elevation_profile

router = APIRouter(prefix="/api/course", tags=["course"])


class CourseElevationRequest(BaseModel):
    gpx_s3_key: str
    interval_m: float = Field(default=100.0, gt=0, le=1000)


def _s3_client():
    return boto3.client(
        "s3",
        region_name=settings.aws_default_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


def download_gpx_text(gpx_s3_key: str) -> str:
    key = gpx_s3_key.lstrip("/")
    if not key.startswith("race-courses/"):
        raise ValueError("gpx_s3_key는 race-courses/ 로 시작해야 합니다.")
    obj = _s3_client().get_object(Bucket=settings.aws_bucket, Key=key)
    return obj["Body"].read().decode("utf-8", errors="replace")


@router.post("/elevation")
def course_elevation(req: CourseElevationRequest):
    try:
        gpx_text = download_gpx_text(req.gpx_s3_key)
        return build_elevation_profile(gpx_text, req.interval_m)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"고저도 파싱 실패: {e}") from e


@router.post("/elevation/upload")
async def course_elevation_upload(
    file: UploadFile = File(...),
    interval_m: float = Form(default=100.0),
):
    """로컬 테스트용 — multipart GPX 업로드."""
    if interval_m <= 0 or interval_m > 1000:
        raise HTTPException(status_code=400, detail="interval_m은 0~1000 사이여야 합니다.")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    try:
        return build_elevation_profile(raw.decode("utf-8", errors="replace"), interval_m)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"고저도 파싱 실패: {e}") from e
