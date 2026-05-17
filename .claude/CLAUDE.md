# CORE 프로젝트 - Claude Code 지침

> AI 분석 / 크롤링 전담 Python FastAPI 서버
> 공통 정의서 참고: ./project-definition.md

---

## 문서 자동 갱신 규칙

아래 시점에 **반드시** `.claude/project-definition.md` 와 `../project-definition.md` 를 최신 상태로 업데이트한다.

**트리거 조건**
1. 새 API 엔드포인트 구현 완료 후 git commit 직전
2. 사용자가 `/compact` 를 실행하기 전 (또는 컨텍스트 압축 직전)
3. 사용자가 "정의서 업데이트", "문서 갱신" 등을 요청할 때

**업데이트 항목**
- API 엔드포인트 현황 (구현 완료 ✅ 표시)
- 새로 추가된 라우터 / 서비스 파일
- 변경된 요청/응답 스펙
- 새로운 외부 서비스 연동
- 크롤링 대상 추가/변경

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
1. FastAPI 기본 설치 및 Supabase 연결  ✅ 완료
2. Swagger UI 확인                     ✅ 완료
3. 이미지 파싱 API (GPT-4o Vision)     ✅ 완료 (DB 저장 연결)
4. 날씨 데이터 API (기상청)            ← 다음 작업
5. 리뷰 요약 API (Claude API)
```

## 서버 인프라 (완료)

```
EC2: t3.micro / Ubuntu 24.04 / 13.125.109.144
도메인: api.pac-run.com (HTTPS, Let's Encrypt)
배포 경로: /var/www/fastapi
서비스: systemd (core-api.service, 자동시작)
```

## AI 서비스

```
이미지 파싱: OpenAI GPT-4o (OPENAI_API_KEY)
리뷰 요약/감정분석: 추후 설정
```

## 브랜치 규칙

```
dev  → 로컬 개발 (push/pull 기본)
main → EC2 운영서버 (git pull)
```

---

## 주의사항

- 과도한 기능 추가 자제 (v1 은 작게 시작)
- 운영 환경에서 Swagger 반드시 비활성화
- Claude API Key 는 .env 관리 / Git 커밋 금지
- Apify 비용 모니터링 필수
