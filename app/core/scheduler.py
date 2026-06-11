"""
APScheduler 설정 (app/core/scheduler.py)

FastAPI lifespan 에서 시작/종료.
현재 등록된 작업:
  - daily_backup    : 매일 00:00 KST — DB 전체 백업
  - wa_label_sync   : 매년 12월 1일 02:00 KST — WA 라벨 대회 목록 갱신
                      (World Athletics 연 1회 11월 발표 → 12월 1일 자동 수집)
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

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
    from app.services.race_crawler import crawl_wa_label_races, parse_wa_race_date
    from app.core.database import review_db

    next_year = datetime.now().year + 1  # 12월 발표 기준 → 다음 해 대회 목록
    logger.info(f"[스케줄] WA 라벨 대회 갱신 시작 — {next_year}년")

    races = crawl_wa_label_races(next_year)
    if not races:
        logger.warning(f"[스케줄] WA 라벨 대회 없음 — {next_year}년 (Wikipedia 페이지 미생성 가능)")
        return

    existing_res = review_db().table("races").select("id,name,wa_label").execute()
    existing_by_name = {r["name"].lower(): r for r in (existing_res.data or [])}

    inserted = updated = skipped = 0
    for race in races:
        cert_payload = {
            "wa_label":     race["wa_label"],
            "is_certified": True,
            "source":       "world_athletics",
            "source_url":   race.get("source_url", ""),
        }
        existing = existing_by_name.get(race["name"].lower())
        if existing:
            if existing.get("wa_label") == race["wa_label"]:
                skipped += 1
                continue
            review_db().table("races").update(cert_payload).eq("id", existing["id"]).execute()
            updated += 1
        else:
            review_db().table("races").insert({
                "name":      race["name"],
                "city":      race.get("city", ""),
                "race_date": parse_wa_race_date(race.get("date", ""), next_year),
                "is_active": True,
                "status":    "active",
                **cert_payload,
            }).execute()
            inserted += 1

    logger.info(f"[스케줄] WA 라벨 갱신 완료 — {next_year}년: 신규 {inserted} / 갱신 {updated} / 동일 {skipped}")


def start() -> None:
    scheduler.add_job(
        _backup_job,
        CronTrigger(hour=0, minute=0, timezone="Asia/Seoul"),
        id="daily_backup",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _wa_sync_job,
        CronTrigger(month=12, day=1, hour=2, minute=0, timezone="Asia/Seoul"),
        id="wa_label_sync",
        replace_existing=True,
        misfire_grace_time=86400,  # 당일 내 missfire 허용
    )
    scheduler.start()
    logger.info("[스케줄러] 시작 — daily_backup 매일 00:00 KST / wa_label_sync 매년 12/1 02:00 KST")


def stop() -> None:
    scheduler.shutdown(wait=False)
    logger.info("[스케줄러] 종료")
