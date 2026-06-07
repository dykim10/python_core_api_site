"""
기상청 API Hub 서비스 (app/services/kma_service.py)

[제공 기능]
  fetch_stations()                    : stn_inf.php → 전국 지상 관측소 목록 (list[dict])
  upsert_stations(live)               : weather_stations 테이블 upsert (stn_id 기준)
  fetch_observation(stn, tm)          : kma_sfctm2.php → 특정 지점·시각 기상 관측값 (dict)
  infer_station_with_claude(loc,city) : Claude AI 로 장소명 → 기상청 지점코드 추론

[KMA 응답 형식]
  stn_inf.php     : 텍스트 (#START7777 ~ #7777END), 직접 파싱
  kma_sfctm2.php  : disp=1 → JSON 응답

[외부 API 수신 규칙]
  - 수신은 JSON 우선, 텍스트 응답은 파싱 후 dict 변환
  - 원본 raw_data JSONB 보존
  - fetched_at TIMESTAMPTZ 필수 기록
"""
import json
from datetime import datetime, timezone
from typing import Optional

import anthropic
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


# ── Claude AI 장소 → 지점코드 추론 ────────────────────────────────────────────

# 전국 주요 지점 목록 (추론 힌트용)
_STN_LIST_HINT = """
108=서울/반포/여의도/잠실/뚝섬/강남/마포/홍대/신촌/연세/광화문/이태원/한강
112=인천/부천/인천공항
119=수원/군포/안양/의왕/화성/평택/오산
98=의정부/동두천/고양/파주/양주
202=양평/가평/이천
101=춘천/홍천
105=강릉/동해/삼척
90=속초/양양
114=원주
133=대전/세종/천안/공주
131=청주/충주/음성
146=전주/익산/군산
156=광주/나주/목포
168=여수/순천/광양
143=대구/경산/영천
159=부산/김해/양산
155=창원/마산/진해
152=울산
136=경주/포항
184=제주
"""


def infer_station_with_claude(location: str, city: str = "") -> Optional[int]:
    """
    Claude AI 를 사용해 장소명 / 도시명 → 가장 가까운 KMA 지점코드 추론.

    location : 장소 텍스트 (예: "여의도공원", "이순신로")
    city     : 도시 텍스트 (예: "서울", "인천") — 없으면 빈 문자열

    반환: int(지점코드) or None(추론 실패)
    """
    if not settings.anthropic_api_key:
        return None

    prompt = f"""아래 한국 마라톤/러닝 대회 장소 정보를 보고, 가장 적합한 기상청 관측 지점코드를 선택해주세요.

장소명: {location or "(없음)"}
도시/시·군·구: {city or "(없음)"}

기상청 지점 참고표:
{_STN_LIST_HINT.strip()}

규칙:
1. 장소명과 도시 정보를 종합해 가장 가까운 지점코드를 선택하세요.
2. 확실하지 않으면 서울(108)을 기본값으로 사용하세요.
3. JSON 만 반환하세요. 설명 없음.

반환 형식: {{"stn_id": 108, "region": "서울", "confidence": "high"}}"""

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=128,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        # JSON 부분만 추출
        start = text.find("{")
        end   = text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])
            return int(data.get("stn_id", 108))
    except Exception:
        pass

    return None
