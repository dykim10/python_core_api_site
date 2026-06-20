"""
대회 정보 CRUD 라우터 (app/api/routes/races.py)
"""
from datetime import datetime
from fastapi import APIRouter, HTTPException
from app.core.database import review_db
from app.services.race_crawler import crawl_wa_label_races
from app.services.wa_sync_service import sync_wa_label_races
from typing import List

router = APIRouter(prefix="/api/races", tags=["races"])


@router.get("/crawl-wa-labels", response_model=List[dict])
def get_wa_label_races(year: int = 0, organiser: bool = False):
    """World Athletics Label Road Races 캘린더를 GraphQL로 수집해 반환한다."""
    target_year = year if year > 0 else datetime.now().year
    races = crawl_wa_label_races(target_year, fetch_organiser=organiser)
    if not races:
        raise HTTPException(
            status_code=404,
            detail=f"{target_year}년 WA 라벨 대회 목록을 가져올 수 없습니다.",
        )
    return races


@router.get("/", response_model=List[dict])
def get_races(limit: int = 20):
    res = (
        review_db()
        .table("races")
        .select("*")
        .eq("is_active", True)
        .order("id", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data


@router.post("/sync", response_model=dict)
def sync_wa_label_races_endpoint(
    year: int = 0,
    translate: bool = True,
    organiser: bool = True,
):
    """WA 라벨 대회를 review.races + review.race_editions에 upsert한다."""
    target_year = year if year > 0 else datetime.now().year
    result = sync_wa_label_races(
        target_year,
        translate=translate,
        fetch_organiser=organiser,
    )
    if result["total"] == 0:
        raise HTTPException(
            status_code=404,
            detail=f"{target_year}년 WA 라벨 대회를 가져올 수 없습니다.",
        )
    return result


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
