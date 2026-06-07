# 기상청 API Hub — 날씨 연동 설계서

> 작성일: 2026-06-07  
> 대상: CORE API `GET /api/weather` 엔드포인트 구현 참고

---

## 1. API Hub 기본 정보

| 항목 | 내용 |
|---|---|
| 포털 | https://apihub.kma.go.kr |
| 인증 | 쿼리 파라미터 `authKey=<발급키>` |
| 응답 형식 | CSV (기본) / JSON (`disp=json` 파라미터) |
| 요금 | 일반 조회 무료 (대용량은 별도 신청) |

---

## 2. 수신 및 저장 규칙

### 수신 형식 — JSON 고정

모든 기상청 API 호출 시 **JSON 응답**을 명시적으로 요청한다.

```python
import requests, json

url    = "https://apihub.kma.go.kr/api/typ01/url/kma_sfctm2.php"
params = {
    "authKey": KMA_API_KEY,
    "tm":      "202606071200",
    "stn":     "108",
    "disp":    "1",          # JSON 응답 강제
}

response = requests.get(url, params=params)
data     = response.json()   # dict 변환 후 DB 저장
```

> 일부 구형 API(`stn_inf.php` 등)는 텍스트 반환 → 파싱 후 dict 변환하여 동일하게 처리

### 저장 규칙
- 수신 원본(JSON) 보존 원칙 — 가공값은 별도 컬럼
- `fetched_at TIMESTAMPTZ` 컬럼 필수 포함
- 저장 대상: `review.race_weather`

---

## 3. 사용 API 2종

### 3-1. 지점정보 조회

```
GET /api/typ01/url/stn_inf.php
```

| 파라미터 | 값 | 설명 |
|---|---|---|
| `authKey` | 발급키 | 필수 |
| `inf_type` | `SFC` | 지상 관측소 |
| `stn` | 지점코드 또는 `STN_ALL` | 전체 조회 시 STN_ALL |
| `disp` | `1` | JSON 응답 |

**응답 주요 필드**

| 필드 | 설명 |
|---|---|
| `stn_id` | 지점 코드 |
| `stn_ko` | 지점명 (한국어) |
| `lat` | 위도 |
| `lon` | 경도 |
| `ht` | 고도 (m) |

---

### 3-2. 지상(종관) 기상관측 — ASOS

```
GET /api/typ01/url/kma_sfctm2.php
```

| 파라미터 | 값 | 설명 |
|---|---|---|
| `authKey` | 발급키 | 필수 |
| `tm` | `YYYYMMDDHHmm` | 관측 시각 (정시) |
| `stn` | 지점코드 | 예: `108` (서울) |
| `disp` | `1` | JSON 응답 |

**응답 주요 필드**

| 필드 | 설명 | DB 매핑 |
|---|---|---|
| `ta` | 기온 (°C) | `temperature` |
| `hm` | 상대습도 (%) | `humidity` |
| `ws` | 풍속 (m/s) | `wind_speed` |
| `rn_day` | 일강수량 (mm) | — |
| `wd` | 풍향 (°) | — |
| `wc` | 날씨코드 | `weather_condition` 변환 필요 |

---

## 4. PAC-RUN 지부별 지점코드 매핑

| 지부 | 지점명 | ASOS 코드 | 위도 | 경도 | 비고 |
|---|---|---|---|---|---|
| 반포 | 서울 | **108** | 37.5714 | 126.9660 | 서울 대표 관측소 |
| 연대 | 서울 | **108** | 37.5714 | 126.9660 | 동일 |
| 인천 | 인천 | **112** | 37.4774 | 126.6247 | 인천 공항 인근 |
| 군포 | 수원 | **119** | 37.2681 | 126.9876 | 군포 최근접 관측소 |

### 기타 대회 개최지 주요 코드

| 지역 | 지점명 | 코드 |
|---|---|---|
| 경기 동부 | 양평 | 202 |
| 강원 | 춘천 | 101 |
| 강원 동해 | 강릉 | 105 |
| 충청 | 대전 | 133 |
| 전라 | 광주 | 156 |
| 경상 | 부산 | 159 |
| 제주 | 제주 | 184 |

---

## 5. CORE API 구현 계획

### 엔드포인트

```
GET /api/weather?stn=108&tm=202606071200
GET /api/weather?lat=37.5&lon=126.9&tm=202606071200   # 좌표 → 최근접 지점 자동 매핑
```

### 파일 구조

```
app/
  api/
    routes/
      weather.py        ← 신규 라우터
    services/
      kma_service.py    ← KMA API 호출 + 파싱
      stn_resolver.py   ← 좌표 → 최근접 지점코드 변환 (Haversine)
```

### 처리 흐름

```
요청 (stn 또는 lat/lon + tm)
  ↓
stn_resolver: 좌표 입력 시 전국 지점 목록에서 최근접 지점 탐색
  ↓
kma_service: ASOS API 호출 (tm 기준 ±1시간 fallback 포함)
  ↓
weather_condition 코드 → 한국어 매핑
  (1=맑음, 2=구름많음, 3=흐림, 4=비, 5=눈, 6=빗속의눈, ...)
  ↓
JSON 응답: { temperature, humidity, wind_speed, weather_condition, stn_id, stn_name }
```

### REVIEW 연동 흐름

```
대회 등록/수정 (race.date + race.location)
  ↓
CORE API GET /api/weather?stn=<지점코드>&tm=<대회날짜 09:00>
  ↓
review.race_weather INSERT
  { race_id, temperature, humidity, wind_speed, weather_condition }
```

---

## 6. weather_condition 코드 매핑표

| 코드 | 한국어 | 영문 |
|---|---|---|
| 1 | 맑음 | clear |
| 2 | 구름 조금 | partly_cloudy |
| 3 | 구름 많음 | mostly_cloudy |
| 4 | 흐림 | cloudy |
| 5 | 비 | rain |
| 6 | 눈 | snow |
| 7 | 비+눈 | sleet |
| 8 | 소나기 | shower |
| 9 | 안개 | fog |

---

## 7. .env 추가 항목

```dotenv
# 기상청 API Hub
KMA_API_KEY=<발급키>
KMA_API_BASE=https://apihub.kma.go.kr/api/typ01/url
```

---

## 8. 구현 우선순위

- [ ] `kma_service.py` — ASOS 단건 조회
- [ ] `stn_resolver.py` — 지점코드 목록 로컬 캐시 + 최근접 탐색
- [ ] `GET /api/weather` 라우터 등록
- [ ] REVIEW `RaceController` — 대회 저장 시 날씨 자동 수집 연동
- [ ] `review.race_weather` 데이터 채우기 (기존 대회 소급 적용)
