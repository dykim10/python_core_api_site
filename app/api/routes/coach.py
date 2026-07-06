"""
AI 코치 라우터 (app/api/routes/coach.py)

POST /api/coach/pb/parse
POST /api/coach/inbody/parse
POST /api/coach/body-records
GET  /api/coach/body-records/{user_id}
POST /api/coach/feedback/{log_id}
POST /api/coach/weekly-report
POST /api/coach/schedule/generate
"""
import logging
from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.services import body_service, coach_service
from app.services import pb_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/coach", tags=["coach"])


class BodyRecordRequest(BaseModel):
    user_id: int
    measured_at: str
    weight_kg: float = Field(..., ge=30, le=150)
    skeletal_muscle_kg: Optional[float] = None
    body_fat_kg: Optional[float] = None
    bmi: Optional[float] = None
    body_fat_percent: Optional[float] = None
    inbody_score: Optional[int] = None
    source: Literal["manual", "image"] = "manual"
    image_url: Optional[str] = None


class WeeklyReportRequest(BaseModel):
    user_id: int
    week_start: date


class ScheduleGenerateRequest(BaseModel):
    user_id: int
    week_start: date


@router.post("/pb/parse")
async def parse_pb(file: UploadFile = File(...)):
    """PB 기록 이미지 1회성 파싱 — S3·DB 저장 없음, 폼 자동입력용."""
    try:
        return await pb_service.parse_pb_upload(file)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Coach] PB 파싱 오류: {type(e).__name__}")
        raise HTTPException(status_code=502, detail="PB 이미지 파싱에 실패했습니다.") from e


@router.post("/inbody/parse")
async def parse_inbody(file: UploadFile = File(...)):
    """인바디 이미지 파싱 — DB 저장 없음."""
    try:
        image_bytes, media_type = await body_service.read_image_upload(file)
        return body_service.parse_inbody_image(image_bytes, media_type)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Coach] 인바디 파싱 오류: {type(e).__name__}")
        raise HTTPException(status_code=502, detail="인바디 이미지 파싱에 실패했습니다.") from e


@router.post("/body-records")
def create_body_record(req: BodyRecordRequest):
    try:
        return body_service.store_body_record(req.model_dump())
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail="체성분 저장 설정 오류입니다.") from e
    except Exception as e:
        logger.error(f"[Coach] body-records 저장 오류: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="체성분 저장에 실패했습니다.") from e


@router.get("/body-records/{user_id}")
def list_body_records(user_id: int, limit: int = 12):
    try:
        return {"records": body_service.get_body_records(user_id, limit=limit)}
    except Exception as e:
        logger.error(f"[Coach] body-records 조회 오류: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="체성분 조회에 실패했습니다.") from e


@router.post("/feedback/{log_id}")
def feedback(log_id: int):
    try:
        return coach_service.generate_feedback(log_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error(f"[Coach] 피드백 오류 log_id={log_id}: {type(e).__name__}")
        raise HTTPException(status_code=502, detail="AI 코치 피드백 생성에 실패했습니다.") from e


@router.post("/weekly-report")
def weekly_report(req: WeeklyReportRequest):
    try:
        return coach_service.generate_weekly_report(req.user_id, req.week_start)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error(f"[Coach] 주간 리포트 오류: {type(e).__name__}")
        raise HTTPException(status_code=502, detail="주간 리포트 생성에 실패했습니다.") from e


@router.post("/schedule/generate")
def schedule_generate(req: ScheduleGenerateRequest):
    try:
        return coach_service.generate_schedule(req.user_id, req.week_start)
    except Exception as e:
        logger.error(f"[Coach] 스케줄 생성 오류: {type(e).__name__}")
        raise HTTPException(status_code=502, detail="주간 스케줄 생성에 실패했습니다.") from e
