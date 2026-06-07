"""
날씨 라우터 (app/api/routes/weather.py)

[엔드포인트]
  GET  /api/weather/stations
    DB 저장된 지점 목록 조회 (로컬 또는 LIVE)
    ?live=false

  POST /api/weather/stations/sync
    기상청 API → weather_stations 테이블 upsert
    ?live=false   로컬만
    ?live=true    LIVE만
    ?live=both    로컬 + LIVE 동시

  GET  /api/weather/observation
    특정 지점·시각 기상 관측값 조회 (DB 저장 없음 — 실시간 API 호출)
    ?stn=108&tm=202606071200

  POST /api/weather/race/{race_id}
    대회 ID → 대회일 날씨 조회 → race_weather upsert
    ?live=false
"""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.core.database import review_db
from app.services import kma_service

router = APIRouter(prefix="/api/weather", tags=["weather"])


# ── 지점 목록 조회 ────────────────────────────────────────────────────────────

@router.get("/stations")
def get_stations(
    live: bool = Query(False, description="True = LIVE DB, False = 로컬 DB"),
    limit: int = Query(200, le=500),
):
    res = (
        review_db(live=live)
        .table("weather_stations")
        .select("stn_id, stn_name, lat, lon, ht")
        .order("stn_id")
        .limit(limit)
        .execute()
    )
    return {"db": "LIVE" if live else "LOCAL", "count": len(res.data), "stations": res.data}


# ── 지점 정보 동기화 ──────────────────────────────────────────────────────────

@router.post("/stations/sync")
def sync_stations(
    target: Literal["local", "live", "both"] = Query(
        "local", description="local | live | both"
    ),
):
    """기상청 stn_inf.php → weather_stations upsert."""
    try:
        stations = kma_service.fetch_stations()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"기상청 API 오류: {e}")

    if not stations:
        raise HTTPException(status_code=502, detail="기상청 응답에 지점 데이터 없음")

    results = {}

    if target in ("local", "both"):
        results["local"] = kma_service.upsert_stations(stations, live=False)

    if target in ("live", "both"):
        results["live"] = kma_service.upsert_stations(stations, live=True)

    return {
        "fetched": len(stations),
        "results": results,
    }


# ── 실시간 관측값 조회 ────────────────────────────────────────────────────────

@router.get("/observation")
def get_observation(
    stn: int  = Query(..., description="지점코드 (예: 108)"),
    tm:  str  = Query(..., description="관측 시각 YYYYMMDDHHmm (예: 202606071200)"),
):
    """기상청 ASOS 실시간 조회 (DB 저장 없음)."""
    try:
        data = kma_service.fetch_observation(stn_id=stn, tm=tm)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"기상청 API 오류: {e}")

    if data is None:
        raise HTTPException(status_code=404, detail="해당 지점·시각 관측 데이터 없음")

    return data


# ── 대회 날씨 저장 ────────────────────────────────────────────────────────────

@router.post("/race/{race_id}")
def save_race_weather(
    race_id: int,
    live: bool = Query(False),
    hour:  int = Query(9, ge=0, le=23, description="대회 시작 시각 (기본 오전 9시)"),
):
    """
    races 테이블에서 대회일 조회 → ASOS 날씨 fetch → race_weather upsert.
    지점코드는 대회 location 기반 매핑 (미매핑 시 서울 108 사용).
    """
    db = review_db(live=live)

    # 대회 정보 조회
    race_res = db.table("races").select("id, name, race_date, location").eq("id", race_id).single().execute()
    if not race_res.data:
        raise HTTPException(status_code=404, detail="대회 없음")

    race     = race_res.data
    race_date = race["race_date"]  # "YYYY-MM-DD"

    # 날짜 → KMA tm 포맷
    dt = datetime.strptime(race_date, "%Y-%m-%d").replace(hour=hour)
    tm = dt.strftime("%Y%m%d%H00")

    # 지역 → 지점코드 매핑
    stn_id = _resolve_stn(race.get("location", ""))

    # 기상청 조회
    try:
        obs = kma_service.fetch_observation(stn_id=stn_id, tm=tm)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"기상청 API 오류: {e}")

    if obs is None:
        raise HTTPException(status_code=404, detail=f"날씨 데이터 없음 (stn={stn_id}, tm={tm})")

    # race_weather upsert (race_id 기준)
    row = {
        "race_id":           race_id,
        "stn_id":            stn_id,
        "temperature":       obs["temperature"],
        "humidity":          obs["humidity"],
        "wind_speed":        obs["wind_speed"],
        "weather_condition": obs["weather_condition"],
        "raw_data":          obs["raw_data"],
        "fetched_at":        obs["fetched_at"],
    }
    db.table("race_weather").upsert(row, on_conflict="race_id").execute()

    return {
        "race_id":  race_id,
        "race_name": race["name"],
        "stn_id":   stn_id,
        "tm":       tm,
        "weather":  obs,
    }


# ── 지역명 → 지점코드 매핑 ───────────────────────────────────────────────────

_LOCATION_MAP: dict[str, int] = {
    # 수도권
    "서울": 108, "반포": 108, "여의도": 108, "마포": 108,
    "연세": 108, "신촌": 108, "홍대": 108,
    "인천": 112, "부천": 112,
    "수원": 119, "군포": 119, "안양": 119, "의왕": 119,
    "성남": 108, "분당": 108, "판교": 108,
    # 경기
    "양평": 202, "가평": 202,
    "의정부": 98, "동두천": 98,
    # 강원
    "춘천": 101, "강릉": 105, "속초": 90,
    "원주": 114, "철원": 95,
    # 충청
    "대전": 133, "청주": 131, "천안": 232,
    # 전라
    "광주": 156, "전주": 146, "여수": 168,
    # 경상
    "부산": 159, "대구": 143, "울산": 152,
    "창원": 155, "경주": 136,
    # 제주
    "제주": 184,
}

def _resolve_stn(location: str) -> int:
    """지역명 문자열에서 가장 먼저 매칭되는 지점코드 반환. 없으면 서울(108)."""
    for keyword, code in _LOCATION_MAP.items():
        if keyword in (location or ""):
            return code
    return 108  # 기본값: 서울
