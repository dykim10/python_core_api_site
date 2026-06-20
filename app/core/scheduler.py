"""
APScheduler 설정 (app/core/scheduler.py)

FastAPI lifespan 에서 시작/종료.
현재 등록된 작업:
  - daily_backup           : 매일 00:00 KST — DB 전체 백업
  - wa_label_sync          : 매년 12월 1일 02:00 KST — WA 라벨 대회 목록 갱신
  - weekly_crew_mailing    : 매주 월요일 06:00 KST — 주간 크루 뉴스레터 발송
  - weekly_mailing_test    : 서버 시작 후 90분 1회 — 테스트 발송 (MAILING_TEST_EMAIL 설정 시)
"""
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Seoul")


def _backup_job() -> None:
    from app.services.backup_service import run_backup
    result = run_backup()
    if result.get("success"):
        logger.info(f"[스케줄] 백업 완료: {result}")
    else:
        logger.error(f"[스케줄] 백업 실패: {result.get('error')}")


def _wa_sync_job() -> None:
    from datetime import datetime
    from app.services.wa_sync_service import sync_wa_label_races

    next_year = datetime.now().year + 1
    logger.info(f"[스케줄] WA 라벨 대회 갱신 시작 — {next_year}년")

    result = sync_wa_label_races(
        next_year,
        translate=True,
        fetch_organiser=False,
    )
    if result["total"] == 0:
        logger.warning(f"[스케줄] WA 라벨 대회 없음 — {next_year}년")
        return

    logger.info(
        "[스케줄] WA 라벨 갱신 완료 — %s년: races +%d/~%d editions +%d/~%d skipped %d",
        next_year,
        result["races_inserted"],
        result["races_updated"],
        result["editions_inserted"],
        result["editions_updated"],
        result["skipped"],
    )


def _weekly_mailing_job() -> None:
    from app.services.mailing_service import send_weekly_mailing
    logger.info("[스케줄] 주간 크루 뉴스레터 발송 시작")
    result = send_weekly_mailing(live=True)
    if result.get("success"):
        logger.info(f"[스케줄] 주간 뉴스레터 완료: 발송 {result.get('sent')}건 / 실패 {result.get('failed')}건")
    else:
        logger.error(f"[스케줄] 주간 뉴스레터 실패: {result.get('reason')}")


def _race_summary_batch_job() -> None:
    from app.services.race_summary_batch import batch_pending_race_summaries
    logger.info("[스케줄] 대회 종합 AI 요약 배치 시작")
    result = batch_pending_race_summaries(live=True)
    logger.info(f"[스케줄] 대회 종합 AI 요약 배치 완료: {result}")


def start() -> None:
    scheduler.add_job(
        _backup_job,
        CronTrigger(hour=0, minute=0, timezone="Asia/Seoul"),
        id="daily_backup",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _race_summary_batch_job,
        CronTrigger(hour=3, minute=0, timezone="Asia/Seoul"),
        id="batch_race_summaries",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _wa_sync_job,
        CronTrigger(month=12, day=1, hour=2, minute=0, timezone="Asia/Seoul"),
        id="wa_label_sync",
        replace_existing=True,
        misfire_grace_time=86400,
    )
    scheduler.add_job(
        _weekly_mailing_job,
        CronTrigger(day_of_week="mon", hour=6, minute=0, timezone="Asia/Seoul"),
        id="weekly_crew_mailing",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # 서버 시작 후 90분 1회 테스트 발송 (MAILING_TEST_EMAIL 환경변수 설정 시에만)
    from app.core.config import settings
    from zoneinfo import ZoneInfo
    test_email = getattr(settings, "mailing_test_email", None)
    if test_email:
        kst = ZoneInfo("Asia/Seoul")
        run_at = datetime.now(tz=kst) + timedelta(minutes=90)
        scheduler.add_job(
            lambda: _run_test_mailing(test_email),
            DateTrigger(run_date=run_at),
            id="weekly_mailing_test",
            replace_existing=True,
        )
        logger.info(f"[스케줄러] 테스트 발송 예약 → {run_at.strftime('%H:%M KST')} ({test_email})")

    scheduler.start()
    logger.info(
        "[스케줄러] 시작 — "
        "daily_backup 매일 00:00 KST / "
        "batch_race_summaries 매일 03:00 KST / "
        "wa_label_sync 매년 12/1 02:00 KST / "
        "weekly_crew_mailing 매주 월요일 06:00 KST"
    )


def _run_test_mailing(test_email: str) -> None:
    from app.services.mailing_service import send_weekly_mailing
    logger.info(f"[스케줄] 테스트 발송 실행 → {test_email}")
    result = send_weekly_mailing(test_email=test_email, live=True)
    logger.info(f"[스케줄] 테스트 발송 완료: {result}")


def stop() -> None:
    scheduler.shutdown(wait=False)
    logger.info("[스케줄러] 종료")
