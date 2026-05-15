# CORE 프로젝트 정의서

> 원본 공통 정의서: ~/projects/project-definition.md
> 이 파일은 CORE(Python FastAPI) 프로젝트에 특화된 정의입니다.

---

## 이 프로젝트의 역할

REVIEW / CREW 에서 호출하는 **데이터 수집 / 분석 / AI 처리 전담 API 서버**

```
REVIEW → CORE : 리뷰 AI 요약 / 날씨 / 크롤링
CREW   → CORE : 러닝 이미지 파싱 / 통계
```

---

## 기술 스택

| 구분 | 기술 |
|---|---|
| 언어 | Python 3.14 |
| 프레임워크 | FastAPI |
| DB | Supabase PostgreSQL |
| 통계/분석 | pandas / numpy / scipy |
| 크롤링 | requests / BeautifulSoup |
| SNS 수집 | Apify API |
| AI 분석 | Claude API (Vision / 요약 / 감정분석) |
| 스케줄링 | APScheduler |
| API 문서 | Swagger UI (/docs) / ReDoc (/redoc) |

---

## 경로

| 구분 | 경로 |
|---|---|
| EC2 서버 | `/var/www/fastapi/` |
| 로컬 | `~/projects/core-api/` |
| GitHub | `https://github.com/dykim10/python_core_api_site.git` |

---

## API 접속 주소

```
개발: http://localhost:8000
문서: http://localhost:8000/docs   → Swagger UI
문서: http://localhost:8000/redoc  → ReDoc
운영: Swagger 비활성화 (보안)
```

---

## API 엔드포인트

| 메서드 | 경로 | 설명 | 호출자 |
|---|---|---|---|
| POST | /api/parse-image | 러닝 이미지 파싱 (Claude Vision) | CREW |
| POST | /api/summarize | 리뷰 AI 요약 | REVIEW |
| POST | /api/sentiment | 감정분석 | REVIEW |
| GET | /api/weather | 날씨 데이터 | REVIEW |
| GET | /api/race-info | 대회 정보 크롤링 | REVIEW |

---

## DB 스키마 구조

```
Supabase PostgreSQL
│
├── public 스키마  (공통)
│   ├── users
│   ├── crews
│   ├── branches
│   └── groups
│
├── review 스키마  (REVIEW 전용)
│   ├── races
│   ├── reviews
│   └── race_weather
│
└── crew 스키마   (CREW 전용)
    ├── running_logs
    ├── events
    ├── event_scores
    └── user_goals
```

---

## 이미지 파싱 항목 (Claude Vision)

```
거리 / 평균페이스 / 최고페이스
실내(트레드밀) or 실외(로드)
운동시간 / 칼로리 / 심박수
고도 / 날씨 (있을 경우)
지도 유무
```

---

## 개발 우선순위 (v1)

```
1. FastAPI 기본 설치 및 Supabase 연결  ✅
2. Swagger UI 확인                     ✅
3. 이미지 파싱 API (Claude Vision)
4. 날씨 데이터 API (기상청)
5. 리뷰 요약 API (Claude API)
```

---

## 주의사항

- 과도한 기능 추가 자제 (v1 은 작게 시작)
- 운영 환경에서 Swagger 반드시 비활성화 (`APP_ENV=production`)
- Claude API Key / Supabase Key 는 `.env` 관리 / Git 커밋 금지
- Apify 비용 모니터링 필수
