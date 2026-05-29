"""
S3 파일 관리 라우터 (app/api/routes/s3.py)

CREW(Laravel)에서 호출하는 S3 오브젝트 삭제 엔드포인트.
이미지 파싱 후 러닝 기록 삭제 시 S3 원본 파일을 함께 정리한다.

엔드포인트:
  DELETE /api/s3/image?url={imageUrl}
    - S3 또는 CloudFront CDN URL에서 오브젝트 키를 추출해 삭제
    - URL 패턴: https://{any-domain}/{key}  → key = URL의 path 부분
    - 삭제 실패 시 500 반환 (CREW 측에서 로그만 기록, DB 삭제는 차단하지 않음)
"""
import boto3
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Query
from app.core.config import settings

router = APIRouter(prefix="/api/s3", tags=["s3"])


@router.delete("/image")
async def delete_s3_image(url: str = Query(..., description="삭제할 S3 또는 CDN 이미지 URL")):
    """S3 이미지 삭제 — URL에서 오브젝트 키 자동 추출"""
    parsed = urlparse(url)
    key = parsed.path.lstrip('/')

    if not key:
        raise HTTPException(status_code=400, detail="유효하지 않은 이미지 URL입니다.")

    if not settings.aws_access_key_id or not settings.aws_secret_access_key or not settings.aws_bucket:
        raise HTTPException(status_code=500, detail="S3 설정이 누락되어 있습니다.")

    try:
        s3 = boto3.client(
            "s3",
            region_name=settings.aws_default_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        s3.delete_object(Bucket=settings.aws_bucket, Key=key)
        return {"deleted": key}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"S3 삭제 실패: {str(e)}")
