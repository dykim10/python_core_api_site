"""
백업 관리 라우터 (app/api/routes/backup.py)

엔드포인트:
  POST /api/backup/run
    - 수동 백업 즉시 실행
    - 헤더: X-Backup-Api-Key 필수 (.env BACKUP_API_KEY)

  GET /api/backup/list
    - S3 에 저장된 백업 목록 반환 (최근 30개)
    - 헤더: X-Backup-Api-Key 필수

[보안]
  BACKUP_API_KEY 가 .env 에 설정되지 않았거나 헤더와 불일치하면 403.
  운영 서버에서는 반드시 강력한 무작위 키 사용.
"""
import logging

from fastapi import APIRouter, Header, HTTPException

from app.core.config import settings
from app.services.backup_service import list_backups, run_backup

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backup", tags=["backup"])


def _check_api_key(x_backup_api_key: str | None) -> None:
    if not settings.backup_api_key:
        raise HTTPException(status_code=500, detail="BACKUP_API_KEY 가 서버에 설정되지 않았습니다.")
    if x_backup_api_key != settings.backup_api_key:
        raise HTTPException(status_code=403, detail="유효하지 않은 API 키입니다.")


@router.post("/run", summary="수동 백업 즉시 실행")
async def trigger_backup(
    x_backup_api_key: str | None = Header(default=None),
):
    """
    DB 전체 백업을 즉시 실행합니다.
    스케줄 외 긴급 백업이나 배포 전 스냅샷 용도로 사용합니다.
    """
    _check_api_key(x_backup_api_key)
    result = run_backup()
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result


@router.get("/list", summary="백업 목록 조회")
async def get_backup_list(
    x_backup_api_key: str | None = Header(default=None),
):
    """S3 에 저장된 백업 파일 목록을 최신순으로 반환합니다."""
    _check_api_key(x_backup_api_key)
    return {"backups": list_backups()}
