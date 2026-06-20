"""
날씨 라우터 (app/api/routes/weather.py)

[엔드포인트]
  GET  /api/weather/stations
  POST /api/weather/stations/sync
  GET  /api/weather/observation
  POST /api/weather/resolve-stn   ← 장소명 → 지점코드 추론 (REVIEW 대회 등록 시 호출)
  POST /api/weather/race/{edition_id}
"""
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.database import review_db
from app.services import kma_service

router = APIRouter(prefix="/api/weather", tags=["weather"])


# ── 지점 목록 조회 ────────────────────────────────────────────────────────────

@router.get("/stations")
def get_stations(
    live: bool = Query(False),
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
    target: Literal["local", "live", "both"] = Query("local"),
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

    return {"fetched": len(stations), "results": results}


# ── 실시간 관측값 조회 ────────────────────────────────────────────────────────

@router.get("/observation")
def get_observation(
    stn: int = Query(..., description="지점코드 (예: 108)"),
    tm:  str = Query(..., description="관측 시각 YYYYMMDDHHmm"),
):
    try:
        data = kma_service.fetch_observation(stn_id=stn, tm=tm)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"기상청 API 오류: {e}")

    if data is None:
        raise HTTPException(status_code=404, detail="해당 지점·시각 관측 데이터 없음")
    return data


# ── 장소명 → 지점코드 추론 ────────────────────────────────────────────────────

class ResolveStnRequest(BaseModel):
    location: str = ""
    city:     str = ""

@router.post("/resolve-stn")
def resolve_stn(body: ResolveStnRequest):
    """
    장소명 + 도시명 → KMA 지점코드 추론.
    1차: 키워드 맵
    2차: Claude AI 추론
    REVIEW 대회 등록/수정 시 weather_stn_id 자동 설정에 사용.
    """
    stn_id, method = _resolve_stn_with_fallback(body.location, body.city)
    stn_name = _STN_NAME_MAP.get(stn_id, "")
    return {
        "stn_id":   stn_id,
        "stn_name": stn_name,
        "method":   method,
        "input":    {"location": body.location, "city": body.city},
    }


# ── 대회 날씨 저장 ────────────────────────────────────────────────────────────

@router.post("/race/{edition_id}")
def save_race_weather(
    edition_id: int,
    live: bool = Query(False),
    hour: Optional[int] = Query(None, ge=0, le=23, description="대회 시작 시각 수동 지정 (미지정 시 지역 기본값 자동 적용)"),
):
    """
    race_editions 테이블에서 대회일 조회 → ASOS 날씨 fetch → race_weather upsert.

    edition당 1 row — 이미 수집된 경우 재수집하지 않음.

    지점코드 우선순위:
      1. race_editions.weather_stn_id
      2. 키워드 맵 (location + city)
      3. Claude AI 추론
    """
    db = review_db(live=live)

    existing = (
        db.table("race_weather")
        .select("*")
        .eq("race_edition_id", edition_id)
        .limit(1)
        .execute()
    )
    if existing.data and existing.data[0].get("temperature") is not None:
        row = existing.data[0]
        return {
            "race_edition_id": edition_id,
            "cached": True,
            "stn_id": row.get("stn_id"),
            "weather": row,
        }

    edition_res = (
        db.table("race_editions")
        .select("id, race_id, year, race_date, location, city, weather_stn_id, races(name)")
        .eq("id", edition_id)
        .single()
        .execute()
    )
    if not edition_res.data:
        raise HTTPException(status_code=404, detail="개최 정보 없음")

    edition   = edition_res.data
    race_date = edition.get("race_date")
    if not race_date:
        raise HTTPException(status_code=422, detail="대회일 미등록")

    race = edition.get("races") or {}

    if edition.get("weather_stn_id"):
        stn_id = int(edition["weather_stn_id"])
        method = "manual"
    else:
        stn_id, method = _resolve_stn_with_fallback(
            edition.get("location", ""),
            edition.get("city", "") or race.get("city", ""),
        )
        db.table("race_editions").update({"weather_stn_id": stn_id}).eq("id", edition_id).execute()

    if hour is not None:
        obs_hour, obs_min = hour, 0
    elif stn_id == 108:
        obs_hour, obs_min = 7, 0
    else:
        obs_hour, obs_min = 8, 0

    dt = datetime.strptime(race_date, "%Y-%m-%d").replace(hour=obs_hour, minute=obs_min)
    tm = dt.strftime("%Y%m%d%H%M")

    try:
        obs = kma_service.fetch_observation(stn_id=stn_id, tm=tm)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"기상청 API 오류: {e}")

    if obs is None:
        raise HTTPException(status_code=404, detail=f"날씨 데이터 없음 (stn={stn_id}, tm={tm})")

    row = {
        "race_edition_id":   edition_id,
        "stn_id":            stn_id,
        "temperature":       obs["temperature"],
        "humidity":          obs["humidity"],
        "wind_speed":        obs["wind_speed"],
        "wind_direction":    obs["wind_direction"],
        "precipitation":     obs["precipitation"],
        "weather_condition": obs["weather_condition"],
        "raw_data":          obs["raw_data"],
        "fetched_at":        obs["fetched_at"],
    }
    db.table("race_weather").upsert(row, on_conflict="race_edition_id").execute()

    return {
        "race_edition_id": edition_id,
        "race_name":       race.get("name"),
        "stn_id":          stn_id,
        "stn_name":        _STN_NAME_MAP.get(stn_id, ""),
        "stn_method":      method,
        "tm":              tm,
        "obs_time":        f"{obs_hour:02d}:{obs_min:02d}",
        "weather":         obs,
    }


# ── 지역명 → 지점코드 매핑 ───────────────────────────────────────────────────

_LOCATION_MAP: dict[str, int] = {
    # 서울 전역
    "서울": 108, "서울특별시": 108,
    "강남": 108, "강북": 108, "강동": 108, "강서": 108,
    "반포": 108, "여의도": 108, "잠실": 108, "뚝섬": 108,
    "마포": 108, "홍대": 108, "신촌": 108, "연세": 108,
    "광화문": 108, "종로": 108, "중구": 108, "용산": 108,
    "이태원": 108, "한강": 108, "상암": 108, "목동": 108,
    "구로": 108, "영등포": 108, "관악": 108, "동작": 108,
    "성동": 108, "노원": 108, "도봉": 108, "은평": 108,
    "서초": 108, "송파": 108, "이순신": 108, "광화": 108,
    # 인천 / 경기 서부
    "인천": 112, "인천광역시": 112, "부천": 112, "인천공항": 112,
    # 경기 남부
    "수원": 119, "수원시": 119, "군포": 119, "안양": 119,
    "의왕": 119, "화성": 119, "평택": 119, "오산": 119, "안산": 119,
    # 경기 북부
    "의정부": 98, "동두천": 98, "고양": 98, "파주": 98,
    "양주": 98, "포천": 98, "연천": 98,
    # 경기 동부
    "성남": 108, "분당": 108, "판교": 108, "용인": 119,
    "광주시": 108, "하남": 108, "남양주": 98,
    "양평": 202, "가평": 202, "이천": 202, "여주": 202,
    # 강원
    "춘천": 101, "홍천": 101, "화천": 101,
    "강릉": 105, "동해": 105, "삼척": 105,
    "속초": 90, "양양": 90, "고성": 90,
    "원주": 114, "횡성": 114,
    "철원": 95, "인제": 101,
    "평창": 100, "정선": 100,
    # 충청
    "대전": 133, "대전광역시": 133, "세종": 133,
    "청주": 131, "충주": 131, "음성": 131,
    "천안": 232, "아산": 232, "공주": 133, "논산": 133,
    "서산": 129, "보령": 129, "당진": 129,
    # 전라
    "전주": 146, "익산": 146, "군산": 146, "완주": 146,
    "광주": 156, "광주광역시": 156, "나주": 156, "담양": 156,
    "목포": 165, "순천": 168, "여수": 168, "광양": 168,
    # 경상
    "대구": 143, "대구광역시": 143, "경산": 143, "영천": 143, "칠곡": 143,
    "부산": 159, "부산광역시": 159, "김해": 159, "양산": 159,
    "창원": 155, "마산": 155, "진해": 155, "거제": 155,
    "울산": 152, "울산광역시": 152,
    "경주": 136, "포항": 138,
    "안동": 136, "구미": 143, "영주": 136,
    # 제주
    "제주": 184, "제주특별자치도": 184, "서귀포": 189,
}

# 지점코드 → 한국명 (응답용)
_STN_NAME_MAP: dict[int, str] = {
    108: "서울", 112: "인천", 119: "수원", 98: "의정부",
    202: "양평", 101: "춘천", 105: "강릉", 90: "속초",
    114: "원주", 95: "철원", 100: "대관령",
    133: "대전", 131: "청주", 232: "천안", 129: "서산",
    146: "전주", 156: "광주", 165: "목포", 168: "여수",
    143: "대구", 159: "부산", 155: "창원", 152: "울산",
    136: "경주", 138: "포항", 184: "제주", 189: "서귀포",
}


def _resolve_stn_with_fallback(location: str, city: str) -> tuple[int, str]:
    """
    1차 키워드 맵, 2차 Claude AI.
    반환: (stn_id, method)  method = "keyword" | "claude" | "default"
    """
    combined = f"{city} {location}".strip()

    # 1차: 도시명 우선 매핑 (긴 키워드부터 매칭)
    for keyword in sorted(_LOCATION_MAP, key=len, reverse=True):
        if keyword in combined:
            return _LOCATION_MAP[keyword], "keyword"

    # 2차: Claude AI 추론
    stn_id = kma_service.infer_station_with_claude(location, city)
    if stn_id:
        return stn_id, "claude"

    return 108, "default"
