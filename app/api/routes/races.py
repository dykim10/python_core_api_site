"""
대회 정보 CRUD 라우터 (app/api/routes/races.py)
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, HTTPException
from app.core.database import review_db
from app.services.race_crawler import crawl_wa_label_races
from app.services.wa_sync_service import sync_wa_label_races
from app.services.wa_sync_session import request_cancel
from app.services.pilot_edition_date import lookup_pilot_race_date, lookup_pilot_years
from app.services.race_edition_service import list_upcoming_editions
from app.services.race_catalog_service import list_active_races
from typing import List

router = APIRouter(prefix="/api/races", tags=["races"])


@router.get("/crawl-wa-labels", response_model=List[dict])
def get_wa_label_races(year: int = 0, organiser: bool = False):
    """World Athletics Label Road Races 캘린더를 GraphQL로 수집해 반환한다."""
    target_year = year if year > 0 else datetime.now(ZoneInfo("Asia/Seoul")).year
    races = crawl_wa_label_races(target_year, fetch_organiser=organiser)
    if not races:
        raise HTTPException(
            status_code=404,
            detail=f"{target_year}년 WA 라벨 대회 목록을 가져올 수 없습니다.",
        )
    return races


@router.get("/", response_model=List[dict])
def get_races(limit: int = 20):
    """활성 races 카탈로그 + 최신 edition 날짜(latest_race_date / latest_edition_year)."""
    return list_active_races(limit=limit)


@router.post("/sync/cancel", response_model=dict)
def cancel_wa_label_sync(session_id: str):
    """진행 중인 WA sync 중지 요청 — sync 루프가 감지 후 롤백."""
    if not session_id.strip():
        raise HTTPException(status_code=400, detail="session_id 필요")
    data = request_cancel(session_id.strip())
    return {
        "session_id": session_id,
        "status": "cancelling",
        "cancel_requested": True,
        "previous_status": data.get("status"),
    }


@router.post("/sync", response_model=dict)
def sync_wa_label_races_endpoint(
    year: int = 0,
    translate: bool = False,
    organiser: bool = False,
    session_id: str = "",
):
    """WA 시즌 Label Road Races → races upsert + 연도별 공인/비공인 (editions 없음)."""
    target_year = year if year > 0 else datetime.now(ZoneInfo("Asia/Seoul")).year
    sid = session_id.strip() or None
    result = sync_wa_label_races(
        target_year,
        translate=translate,
        fetch_organiser=organiser,
        session_id=sid,
    )
    if result.get("status") == "cancelled":
        return result
    if result["total"] == 0:
        raise HTTPException(
            status_code=404,
            detail=f"{target_year}년 WA 라벨 대회를 가져올 수 없습니다.",
        )
    return result


@router.get("/pilot-edition-date", response_model=dict)
def get_pilot_edition_date(key: str, year: int, fetch_external: bool = True):
    """국내 pilot 4대회 — 연도별 race_date (catalog → marathongo → null)."""
    if year < 2018 or year > 2035:
        raise HTTPException(status_code=400, detail="year는 2018~2035")
    return lookup_pilot_race_date(key.strip(), year, fetch_external=fetch_external)


@router.get("/pilot-edition-dates", response_model=List[dict])
def get_pilot_edition_dates(
    years: str = "",
    fetch_external: bool = True,
):
    """복수 연도 pilot date 일괄 조회. years=2021,2025,2026"""
    parsed = [int(y.strip()) for y in years.split(",") if y.strip().isdigit()]
    if not parsed:
        raise HTTPException(status_code=400, detail="years 파라미터 필요 (예: 2021,2025)")
    return lookup_pilot_years(parsed, fetch_external=fetch_external)


@router.get("/editions/upcoming", response_model=List[dict])
def get_upcoming_race_editions(limit: int = 80):
    """훈련노트 목표 대회 선택 — upcoming/일정 미정 edition (CREW 전용)."""
    return list_upcoming_editions(limit=limit)


@router.get("/{race_id}", response_model=dict)
def get_race(race_id: int):
    res = (
        review_db()
        .table("races")
        .select("*")
        .eq("id", race_id)
        .single()
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="대회 없음")
    return res.data


@router.post("/", response_model=dict)
def create_race(payload: dict):
    payload.pop("race_date", None)
    res = review_db().table("races").insert(payload).execute()
    if not res.data:
        raise HTTPException(status_code=400, detail="저장 실패")
    return res.data[0]
