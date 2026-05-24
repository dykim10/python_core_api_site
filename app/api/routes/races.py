"""
대회 정보 CRUD 라우터 (app/api/routes/races.py)

review.races 테이블의 대회 데이터를 조회·저장한다.
REVIEW(Laravel) 내부에서 호출하며, 크롤링 결과 upsert 도 이 라우터를 통해 처리한다.

[엔드포인트]
  GET  /api/races/
    활성화된 대회 목록 반환 (is_active=true, race_date 내림차순)
    쿼리 파라미터: limit (기본 20)

  GET  /api/races/{race_id}
    대회 단건 조회 — 없으면 HTTP 404

  POST /api/races/
    대회 신규 등록 (dict payload 자유 형식)
    race_date 가 date 타입이면 문자열로 변환 후 저장
"""
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
