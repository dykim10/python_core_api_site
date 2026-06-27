"""
레이스 플랜 엔드포인트 (app/api/routes/race_plan.py)

REVIEW가 레이스 플랜 생성 버튼을 누를 때 호출한다.

엔드포인트:
  POST /api/race-plan/generate  — 레이스 플랜 생성 (Claude + RAG)
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import race_plan_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/race-plan", tags=["race-plan"])


class GenerateRequest(BaseModel):
    race_edition_id:  int
    user_id:          int
    course_type:      str  = Field(..., pattern="^(FULL|HALF|10K)$")
    goal_time:        str  = Field(..., pattern=r"^\d{1,2}:\d{2}:\d{2}$")
    training_status:  str  = Field("normal", pattern="^(best|good|normal|poor)$")
    recent_long_km:   float | None = Field(None, ge=1, le=200)
    recent_10k_time:  str | None   = Field(None, pattern=r"^\d{1,2}:\d{2}:\d{2}$")
    manual_logs:      list[dict] | None = None
    parsed_image_logs: list[dict] | None = None
    live:             bool = True


@router.post("/generate")
def generate_plan(req: GenerateRequest):
    """
    레이스 플랜 생성.

    대회 정보 + 날씨 + 코스 + RAG 유사 케이스를 조합해
    Claude claude-opus-4-8 으로 개인화 레이스 플랜을 생성한다.
    """
    try:
        plan = race_plan_service.generate(
            race_edition_id=req.race_edition_id,
            user_id=req.user_id,
            course_type=req.course_type,
            goal_time=req.goal_time,
            training_status=req.training_status,
            recent_long_km=req.recent_long_km,
            recent_10k_time=req.recent_10k_time,
            manual_logs=req.manual_logs,
            parsed_image_logs=req.parsed_image_logs,
            live=req.live,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"[RacePlan] 생성 오류: {e}")
        raise HTTPException(status_code=500, detail=f"레이스 플랜 생성 실패: {str(e)}")

    return plan
