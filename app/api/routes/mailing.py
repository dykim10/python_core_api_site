"""
주간 메일링 라우터 (app/api/routes/mailing.py)

POST /api/mailing/send-now
  주간 뉴스레터를 즉시 발송한다 (수동 트리거).
  요청 바디: { test_email?: str, live?: bool }

POST /api/mailing/schedule-test
  90분 후 테스트 발송을 APScheduler 에 등록한다.
  요청 바디: { email: str, live?: bool }

GET /api/mailing/preview
  현재 주간 뉴스레터 HTML 을 반환한다 (브라우저에서 디자인 확인용).
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.services.mailing_service import (
    get_weekly_stats,
    build_weekly_html,
    send_weekly_mailing,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mailing", tags=["mailing"])


class SendNowRequest(BaseModel):
    test_email: Optional[str] = None
    live: bool = True


class ScheduleTestRequest(BaseModel):
    email: str
    live: bool = True
    delay_minutes: int = 90


@router.post("/send-now")
def send_now(req: SendNowRequest):
    """주간 뉴스레터 즉시 발송 (수동 트리거 / 테스트 가능)"""
    try:
        result = send_weekly_mailing(test_email=req.test_email, live=req.live)
        return result
    except Exception as e:
        logger.error(f"[메일링 API] send-now 오류: {e}")
        raise HTTPException(status_code=500, detail=f"발송 실패: {str(e)}")


@router.post("/schedule-test")
def schedule_test(req: ScheduleTestRequest):
    """
    지정된 이메일 주소로 delay_minutes 분 후 테스트 발송을 스케줄에 등록한다.
    기본값: 90분 후 발송.
    """
    try:
        from app.core.scheduler import scheduler
        from apscheduler.triggers.date import DateTrigger

        run_at = datetime.now() + timedelta(minutes=req.delay_minutes)
        email = req.email
        live = req.live

        def _test_job():
            logger.info(f"[메일링] 스케줄 테스트 발송 실행 → {email}")
            send_weekly_mailing(test_email=email, live=live)

        scheduler.add_job(
            _test_job,
            DateTrigger(run_date=run_at, timezone="Asia/Seoul"),
            id="weekly_mailing_test",
            replace_existing=True,
        )

        run_at_str = run_at.strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"[메일링] 테스트 발송 예약 — {run_at_str} → {email}")

        return {
            "success": True,
            "scheduled_at": run_at_str,
            "to": email,
            "message": f"{req.delay_minutes}분 후 ({run_at_str}) 테스트 메일이 발송됩니다.",
        }
    except Exception as e:
        logger.error(f"[메일링 API] schedule-test 오류: {e}")
        raise HTTPException(status_code=500, detail=f"스케줄 등록 실패: {str(e)}")


@router.get("/preview", response_class=HTMLResponse)
def preview():
    """현재 주간 뉴스레터 HTML 미리보기 (브라우저에서 직접 확인)"""
    try:
        stats = get_weekly_stats(live=False)
        html = build_weekly_html(stats)
        return HTMLResponse(content=html)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"미리보기 생성 실패: {str(e)}")
