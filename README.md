# CORE API — AI 분석 / 크롤링 전담 서버

> **REVIEW · CREW 프로젝트의 두뇌 역할**
> AI 이미지 파싱, 리뷰 요약, 대회 크롤링, 날씨 수집 등 무거운 연산을 전담합니다.

- GitHub: https://github.com/dykim10/python_core_api_site.git
- 공통 정의서: `../project-definition.md`

---

## 역할

```
REVIEW (Laravel) ──┐
                   ├──→ CORE API (FastAPI) ──→ GPT / Supabase / 크롤링
CREW   (Laravel) ──┘
```

Laravel 프로젝트들은 직접 AI API를 호출하지 않고, 모두 CORE API를 경유합니다.
CORE API는 같은 EC2에서 실행되며 `http://localhost:8000` 으로 내부 통신합니다.

---

## 기술 스택

| 구분 | 기술 |
|---|---|
| 언어 | Python 3.x |
| 프레임워크 | FastAPI |
| DB | Supabase PostgreSQL |
| AI | GPT-4o-mini (텍스트) / GPT-4o (이미지) |
| 크롤링 | requests / BeautifulSoup |
| SNS 수집 | Apify API (예정) |
| 통계/분석 | pandas / numpy / scipy (예정) |
| 스케줄링 | APScheduler (예정) |
| API 문서 | Swagger UI (`/docs`) — 개발 환경만 활성화 |

---

## API 엔드포인트 현황

### 구현 완료

| 메서드 | 경로 | 설명 | 호출자 |
|---|---|---|---|
| GET | `/` | 헬스 체크 | — |
| GET | `/health/db` | DB 연결 확인 | — |
| POST | `/api/parse-image` | 러닝 앱 스크린샷 → 기록 JSON 파싱 | CREW |
| POST | `/api/summarize` | 리뷰 개별 AI 요약 + 감성분석 | REVIEW |
| POST | `/api/races/summarize` | 대회 전체 리뷰 AI 종합 분석 | REVIEW |
| GET | `/api/races` | 대회 목록 조회 | REVIEW |
| GET | `/api/races/{id}` | 대회 단건 조회 | REVIEW |
| POST | `/api/races` | 대회 등록 | REVIEW |
| GET | `/api/race-info` | 대회 크롤링 수집 | REVIEW |

### 개발 예정

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/weather` | 날씨 데이터 (기상청 / OpenWeatherMap) |
| POST | `/api/sentiment` | 감정분석 독립 호출 |
| GET | `/api/crawl/blogs` | 네이버 블로그 후기 수집 |
| GET | `/api/stats/race/{id}` | 대회 통계 (분포 / 트렌드) |

---

## 이미지 파싱 스펙 (`/api/parse-image`)

러닝 앱(Nike Run Club, Strava, 가민, Apple Watch 등) 스크린샷에서 아래 항목을 추출합니다.

```json
{
  "distance_km": 10.5,
  "avg_pace": "5'30\"/km",
  "best_pace": "4'50\"/km",
  "duration_sec": 3300,
  "calories": 520,
  "avg_heart_rate": 148,
  "is_indoor": false,
  "altitude_m": 85.0
}
```

---

## AI 요약 스펙 (`/api/races/summarize`)

대회별 전체 리뷰(최대 50건)를 종합 분석합니다.

```json
{
  "summary": "전반적으로 코스 관리가 잘 되어 있고...",
  "positives": ["코스 정비 상태 우수", "응원 문화 활발"],
  "negatives": ["주차 공간 부족", "기념품 품질 아쉬움"],
  "keywords": ["초보자 친화적", "가을 경치", "서울 도심"]
}
```

---

## 크롤링 대상

| 사이트 | URL | 방식 |
|---|---|---|
| 마라톤고 | https://marathongo.co.kr | Next.js `__NEXT_DATA__` 파싱 |
| 로드런 | http://www.roadrun.co.kr/schedule/list.php | HTML 테이블 파싱 |

---

## 로컬 개발 환경 설정

```bash
# 1. 가상환경 생성
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 2. 의존성 설치
pip install -r requirements.txt

# 3. 환경 설정
cp .env.example .env
# .env 에서 OPENAI_API_KEY, Supabase 키 설정

# 4. 서버 실행
uvicorn main:app --reload --port 8000

# 5. API 문서 확인
# http://localhost:8000/docs
```

**.env 필수 항목**
```
APP_ENV=development

OPENAI_API_KEY=sk-...

SUPABASE_URL=https://[project-ref].supabase.co
SUPABASE_KEY=[anon-key]
```

---

## EC2 배포

```bash
cd /var/www/fastapi
git pull origin main
pip install -r requirements.txt
sudo systemctl restart core-api
```

---

## 디렉터리 구조

```
core-api/
├── main.py                    FastAPI 앱 진입점
├── app/
│   ├── api/
│   │   └── routes/
│   │       ├── parse_image.py     이미지 파싱
│   │       ├── summarize.py       리뷰 개별 요약
│   │       ├── race_summarize.py  대회 종합 분석
│   │       ├── races.py           대회 CRUD
│   │       ├── race_info.py       크롤링
│   │       ├── running_logs.py    러닝 기록
│   │       └── users.py           회원
│   ├── core/
│   │   ├── config.py             환경 변수
│   │   └── database.py           Supabase 클라이언트
│   ├── models/
│   │   └── schemas.py            Pydantic 스키마
│   └── services/
│       ├── claude_client.py      AI 클라이언트 (현재 GPT 사용)
│       └── race_crawler.py       크롤러
└── scripts/
    ├── analyze_distances.py
    └── normalize_races.py
```

---

## 주의사항

- 운영 환경에서 Swagger(`/docs`, `/redoc`) **반드시 비활성화** (`APP_ENV=production`)
- API Key / Supabase Key는 `.env` 관리, Git 커밋 금지
- Apify 사용 시 비용 모니터링 필수
- CORE API 장애 시 Laravel 메인 기능(리뷰 저장 등)은 정상 동작하도록 try-catch 처리

---

## 관련 프로젝트

| 프로젝트 | 역할 |
|---|---|
| **REVIEW** (Laravel) | 대회 리뷰 플랫폼 — CORE API 호출자 |
| **CREW** (Laravel) | 크루 기록 관리 — CORE API 호출자 |
