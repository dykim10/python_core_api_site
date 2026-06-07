"""
기상청 API Hub 서비스 (app/services/kma_service.py)

[제공 기능]
  fetch_stations()            : stn_inf.php → 전국 지상 관측소 목록 (list[dict])
  upsert_stations(live)       : weather_stations 테이블 upsert (stn_id 기준)
  fetch_observation(stn, tm)  : kma_sfctm2.php → 특정 지점·시각 기상 관측값 (dict)

[KMA 응답 형식]
  stn_inf.php     : 텍스트 (#START7777 ~ #7777END), 직접 파싱
  kma_sfctm2.php  : disp=1 → JSON 응답

[외부 API 수신 규칙]
  - 수신은 JSON 우선, 텍스트 응답은 파싱 후 dict 변환
  - 원본 raw_data JSONB 보존
  - fetched_at TIMESTAMPTZ 필수 기록
"""
import re
from datetime import datetime, timezone
from typing import Optional

import requests

from app.core.config import settings

_BASE = settings.kma_api_base  # https://apihub.kma.go.kr/api/typ01/url


# ── 지점정보 ─────────────────────────────────────────────────────────────────

def fetch_stations() -> list[dict]:
    """
    기상청 stn_inf.php → 전국 지상(SFC) 관측소 목록 반환.

    응답 컬럼 (공백 split 기준):
      cols[0]=STN, cols[1]=LON, cols[2]=LAT, cols[3]=STN_SP,
      cols[4]=HT, cols[5..8]=HT_PA/TA/WD/RN, cols[9]=STN(중복),
      cols[10]=STN_KO(한국명), cols[11]=STN_EN(영문명)
    """
    resp = requests.get(
        f"{_BASE}/stn_inf.php",
        params={
            "authKey": settings.kma_api_key,
            "inf":     "SFC",
            "stn":     "",
            "tm":      datetime.now(timezone.utc).strftime("%Y%m%d%H00"),
        },
        timeout=15,
    )
    resp.raise_for_status()
    # 응답은 EUC-KR 인코딩 — 명시적으로 디코딩
    text = resp.content.decode("euc-kr", errors="replace")
    return _parse_stn_text(text)


def _parse_stn_text(text: str) -> list[dict]:
    """
    #START7777 ~ #7777END 텍스트를 dict 리스트로 변환.

    컬럼 순서 (공백 split):
      [0] STN_ID  [1] LON  [2] LAT  [3] STN_SP  [4] HT
      [9] STN(중복)  [10] STN_KO(한국명)  [11] STN_EN(영문명)
    """
    stations = []
    in_data  = False
    fetched  = datetime.now(timezone.utc).isoformat()

    for line in text.splitlines():
        line = line.strip()
        if line == "#START7777":
            in_data = True
            continue
        if line == "#7777END":
            break
        if not in_data or line.startswith("#") or not line:
            continue

        cols = line.split()
        if len(cols) < 5:
            continue
        try:
            stn_name = cols[10] if len(cols) > 10 else ""
            stations.append({
                "stn_id":     int(cols[0]),
                "stn_name":   stn_name,
                "lon":        float(cols[1]),
                "lat":        float(cols[2]),
                "ht":         float(cols[4]),
                "fetched_at": fetched,
            })
        except (ValueError, IndexError):
            continue

    return stations


# ── 지점정보 DB upsert ────────────────────────────────────────────────────────

def upsert_stations(stations: list[dict], live: bool = False) -> dict:
    """
    weather_stations 테이블에 upsert (stn_id 기준 중복 갱신).

    live=False → 로컬(테스트) DB
    live=True  → 실서버(LIVE) DB
    """
    from app.core.database import review_db

    if not stations:
        return {"upserted": 0}

    db    = review_db(live=live)
    label = "LIVE" if live else "LOCAL"

    # 1000건 단위 청크 upsert
    total = 0
    chunk_size = 500
    for i in range(0, len(stations), chunk_size):
        chunk = stations[i : i + chunk_size]
        db.table("weather_stations").upsert(
            chunk,
            on_conflict="stn_id",
        ).execute()
        total += len(chunk)

    return {"db": label, "upserted": total}


# ── 기상 관측값 ───────────────────────────────────────────────────────────────

def fetch_observation(stn_id: int, tm: str) -> Optional[dict]:
    """
    ASOS 지상 관측 단건 조회.

    stn_id : 지점코드 (예: 108)
    tm     : 관측 시각 YYYYMMDDHHmm (예: "202606071200")

    반환: {temperature, humidity, wind_speed, wind_direction,
           precipitation, weather_condition, stn_id, tm, raw_data, fetched_at}
    None 반환 시 해당 시각 데이터 없음.
    """
    resp = requests.get(
        f"{_BASE}/kma_sfctm2.php",
        params={
            "authKey": settings.kma_api_key,
            "tm":      tm,
            "stn":     stn_id,
            "disp":    "1",   # JSON 응답 강제
        },
        timeout=15,
    )
    resp.raise_for_status()

    raw = resp.json()
    rows = raw.get("response", {}).get("body", {}).get("items", {}).get("item", [])
    if not rows:
        # 일부 API 응답은 최상위 바로 list
        rows = raw if isinstance(raw, list) else []

    if not rows:
        return None

    item     = rows[0] if isinstance(rows, list) else rows
    fetched  = datetime.now(timezone.utc).isoformat()

    return {
        "stn_id":            stn_id,
        "tm":                tm,
        "temperature":       _safe_float(item.get("ta")),
        "humidity":          _safe_float(item.get("hm")),
        "wind_speed":        _safe_float(item.get("ws")),
        "wind_direction":    _safe_float(item.get("wd")),
        "precipitation":     _safe_float(item.get("rn_day")),
        "weather_condition": _wc_to_str(item.get("wc")),
        "raw_data":          item,
        "fetched_at":        fetched,
    }


def _safe_float(val) -> Optional[float]:
    try:
        f = float(val)
        return None if f in (-99.0, -999.0, -9999.0) else f
    except (TypeError, ValueError):
        return None


# weather_condition 코드 → 한국어
_WC_MAP = {
    "1": "맑음", "2": "구름조금", "3": "구름많음", "4": "흐림",
    "5": "비",   "6": "눈",       "7": "진눈깨비", "8": "소나기",
    "9": "안개",
}

def _wc_to_str(code) -> Optional[str]:
    return _WC_MAP.get(str(code)) if code is not None else None
