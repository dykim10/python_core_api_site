# CORE 프로젝트 - Claude Code 지침

> 데이터 수집 / 분석 / 통계 / 스케줄링 전담 Python API 서버
> 공통 정의서 참고: ./project-definition.md

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

## 디렉토리 (EC2 서버)

```
/var/www/fastapi/
```

## 로컬 경로

```
~/projects/core-api/
```

## GitHub

```
https://github.com/dykim10/python_core_api_site.git
```

---

## API 접속 주소

```
개발: http://localhost:8000
문서: http://localhost:8000/docs      → Swagger UI
문서: http://localhost:8000/redoc     → ReDoc
운영: Swagger 비활성화 (보안)
```

---

## 주요 API 엔드포인트 (예정)

```
POST /api/parse-image     → 러닝 이미지 파싱 (CREW 호출)
POST /api/summarize       → 리뷰 AI 요약 (REVIEW 호출)
POST /api/sentiment       → 감정분석
GET  /api/weather         → 날씨 데이터
GET  /api/race-info       → 대회 정보 크롤링
```

---

## 주요 기능

- 이미지 파싱 (Claude Vision API)
- 리뷰 AI 요약 / 감정분석 (Claude API)
- 날씨 데이터 수집 (기상청 API / OpenWeatherMap)
- 크롤링 / 스크래핑 (네이버 블로그 / 유튜브 / Apify)
- 공공데이터 수집 (data.go.kr)
- 통계 / 계산 처리
- 스케줄링 (정기 데이터 수집)

---

## 호출 관계

```
REVIEW → CORE : 리뷰 요약 / 날씨 / 크롤링
CREW   → CORE : 이미지 파싱 / 통계
```

---

## 개발 우선순위 (v1 목표)

```
1. FastAPI 기본 설치 및 AWS EC2 연동
2. Swagger UI 확인
3. 이미지 파싱 API (Claude Vision)
4. 날씨 데이터 API (기상청)
5. 리뷰 요약 API (Claude API)
```

---

## 주의사항

- 과도한 기능 추가 자제 (v1 은 작게 시작)
- 운영 환경에서 Swagger 반드시 비활성화
- Claude API Key 는 .env 관리 / Git 커밋 금지
- Apify 비용 모니터링 필수
