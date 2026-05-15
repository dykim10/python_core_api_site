from fastapi import APIRouter, HTTPException
from app.core.database import review_db
from typing import List

router = APIRouter(prefix="/api/races", tags=["races"])


@router.get("/", response_model=List[dict])
def get_races(limit: int = 20):
    res = (
        review_db()
        .table("races")
        .select("*")
        .eq("is_active", True)
        .order("race_date", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data


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
    if "race_date" in payload:
        payload["race_date"] = str(payload["race_date"])
    res = review_db().table("races").insert(payload).execute()
    if not res.data:
        raise HTTPException(status_code=400, detail="저장 실패")
    return res.data[0]
