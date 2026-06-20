"""
대회 정보 크롤링 라우터 (app/api/routes/race_info.py)

marathongo.co.kr / roadrun.or.kr 크롤링은 2026-06 사용 중단.
"""
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api", tags=["race-info"])

_DISABLED_DETAIL = (
    "marathongo/roadrun 크롤링은 사용 중단되었습니다. "
    "국내 pilot 날짜는 catalog·Admin 수동 입력을 사용하세요."
)


@router.get("/race-info")
def get_race_info(
    source: str = Query(default="all", description="marathongo / roadrun / all (비활성)"),
    limit: int = Query(default=0, le=200, description="소스별 최대 수집 건수 (0=전체)"),
):
    del source, limit
    raise HTTPException(status_code=410, detail=_DISABLED_DETAIL)


@router.get("/race-info/debug")
def debug_race_crawl():
    raise HTTPException(status_code=410, detail=_DISABLED_DETAIL)


@router.get("/race-info/debug-roadrun-detail")
def debug_roadrun_detail(uid: str = Query(description="roadrun 상세 페이지 uid (비활성)")):
    del uid
    raise HTTPException(status_code=410, detail=_DISABLED_DETAIL)
