# 프로젝트 공통 정의서 (초안)

> 작성일: 2026-05-14  
> 목적: Claude 와 사용자 간 협업을 위한 공통 약속어 및 프로젝트 구조 정의

---

## 기술 스택 (공통)

| 구분 | 기술 |
|---|---|
| 서버 | AWS EC2 (t2.micro) |
| 웹서버 | Nginx |
| DB | Supabase PostgreSQL |
| 파일 저장 | AWS S3 + CloudFront |
| 백엔드 웹 | PHP 8.3+ / Laravel |
| 백엔드 API | Python 3.14 / FastAPI |
| 프론트 | HTML / CSS / JS (TBD) |
| 배포 | GitHub → EC2 git pull |
| 인증 | AWS ACM (HTTPS) |
| 이메일 발송 | AWS SES |
| 2단계 인증 | Google OTP (TOTP) 우선 / SMS 는 최후 수단 |
| 단체 문자 | 알리고 or coolsms API (SMS 약 8~10원/건) |

---

## 프로젝트 구성 (3개)

### 1. REVIEW (리뷰 사이트)
> 마라톤/러닝 대회 리뷰 플랫폼

**약속어:** `REVIEW`

**역할**
- 대회 정보 등록 및 조회
- 참가자 리뷰 작성 (인증된 완주자)
- 리뷰 AI 요약 (Claude API 연동)
- SNS 해시태그 수집 (네이버 블로그, 유튜브 등)
- 날씨 데이터 연동 (대회일 날씨 표시)

**기술**
- Laravel (UI 포함)
- Blade 템플릿 / CSS / JS
- Guzzle (CORE-API 호출)

**디렉토리**
```
/var/www/review-site/
```

**회원 테이블 (users)**
```
id / email / password / nickname
created_at / updated_at / last_login_at
```

---

### 2. CREW (러닝 크루 이벤트 사이트)
> 러닝 크루 구성원 기록 관리 및 이벤트 점수 플랫폼

**약속어:** `CREW`

**역할**
- 구성원 러닝 이미지 업로드 → 자동 파싱 → DB 저장
- 개인 기록 관리 (거리 / 페이스 / 실내외 / 날짜 / 고도)
- 조별 기록 관리
- 개인 목표 마일리지 → 달성시 점수 획득
- 이벤트 점수 관리
- 관리자: 통계 / 집계 / 엑셀 다운로드 / 이미지 일괄 다운로드

**기술**
- Laravel (UI 포함)
- Blade 템플릿 / CSS / JS
- Guzzle (CORE-API 호출)
- Claude Vision API (이미지 파싱)

**디렉토리**
```
/var/www/running-crew/
```

**조직 계층**
```
crews      → 크루 (소속 크루)
branches   → 지부 (소속 지부)
groups     → 그룹 (소속 그룹)
```

**주요 테이블**
```
users          : 회원 (이메일/비밀번호/이름/닉네임/크루/지부/그룹)
running_logs   : 러닝 기록 (거리/페이스/실내외/고도/날짜/이미지)
events         : 이벤트 (이벤트명/그룹/날짜/기본점수/메모)
event_scores   : 이벤트 점수 (이벤트/회원/점수/메모)
user_goals     : 개인 목표 (목표마일리지/기간/달성여부/점수)
```

**이미지 파싱 항목**
```
거리 / 평균페이스 / 최고페이스
실내(트레드밀) or 실외(로드)
운동시간 / 칼로리 / 심박수
고도 / 날씨 (있을 경우)
지도 유무
```

---

### 3. CORE (코어 API)
> 데이터 수집 / 분석 / 통계 / 스케줄링 전담 Python 서버

**약속어:** `CORE`

**역할**
- 이미지 파싱 (Claude Vision API)
- 리뷰 AI 요약 / 감정분석
- 날씨 데이터 수집 (기상청 API / OpenWeatherMap)
- 크롤링 / 스크래핑 (네이버 블로그, 유튜브, Apify)
- 공공데이터 수집 (data.go.kr)
- 통계 / 계산 처리
- 스케줄링 (정기 데이터 수집)

**기술**
- Python FastAPI
- pandas / numpy / scipy (통계)
- requests / BeautifulSoup (크롤링)
- Apify (인스타그램 데이터)
- Claude API (AI 분석)
- APScheduler (스케줄링)

**디렉토리**
```
/var/www/fastapi/
```

**내부 통신**
```
REVIEW → CORE : http://localhost:8000/api/...
CREW   → CORE : http://localhost:8000/api/...
```

---

## 회원 정책

**통합 방향:** REVIEW / CREW 회원 테이블 통합 (단일 users 테이블)

**베타 운영 계획**
```
1단계: 클로즈 베타 → 크루 멤버 초대 코드로만 가입
2단계: 오픈 베타   → 이메일 인증 후 누구나 가입
3단계: 정식 오픈   → 완주 인증 등 추가 기능 포함
```

**통합 회원 테이블 (users)**
```
id
email / password / name / nickname
crew_id / branch_id / group_id
role          : super_admin / crew_admin / group_admin / member
is_beta       : 베타 여부
invite_code   : 초대 코드
created_at / updated_at / last_login_at
```

**이메일 (AWS SES)**
```
- 회원가입 이메일 인증
- 비밀번호 재설정
- 초대 코드 발송 (클로즈 베타)
- 이벤트 알림 (추후)
- 주간 러닝 리포트 (추후)
```
> SES 무료 범위: 월 3,000건 (EC2 연동시) / 초과시 1,000건당 $0.10

**2단계 인증 (2FA)**
```
1순위: Google OTP (TOTP) → 무료 / 앱 기반
2순위: SMS 문자 인증     → 유료 / 최후 수단
```
키워드: `Laravel 2FA` `google2fa` `TOTP`

**단체 문자 발송**
```
용도: 공지 / 이벤트 알림 / 크루 단체 발송
```

| 우선순위 | 수단 | 비용 |
|---|---|---|
| 1순위 | 이메일 (AWS SES) | 무료 |
| 2순위 | 앱 푸시 (추후) | 무료 |
| 3순위 | 단체 문자 | 유료 (저렴) |

문자 발송 API 후보
```
알리고   : SMS 약 8~9원 / API 간단 / 국내 최저가
coolsms  : SMS 약 9~10원 / API 문서 좋음
솔라피   : SMS 약 9원 / 한국어 지원 우수
```

> 크루 100명 기준 1회 발송 약 900~1,000원 / 월 10회 약 1만원 이내

키워드: `알리고 API` `coolsms SDK` `Laravel HTTP Client`

---

## ADMIN (관리자)
> 각 사이트 내부 /admin 경로로 운영 (별도 프로젝트 아님)

**약속어:** `ADMIN`

**구현 방식**
```
review.domain.com/admin  → REVIEW 관리자
crew.domain.com/admin    → CREW 관리자
```

**REVIEW 관리자 기능**
```
- 대회 정보 등록 / 수정 / 삭제
- 리뷰 신고 처리
- 회원 관리
- AI 요약 수동 트리거
```

**CREW 관리자 기능**
```
- 구성원 관리 (크루 / 지부 / 그룹)
- 이벤트 등록 / 점수 관리
- 통계 / 집계 조회
- 엑셀 다운로드
- 이미지 일괄 다운로드
```

**기술 키워드**
```
Laravel 미들웨어 / Role / 관리자 권한 분리
```

**권한 구조**
```
super_admin  → 전체 관리
crew_admin   → 크루 단위 관리
group_admin  → 그룹 단위 관리
member       → 일반 구성원
```

---

## 서버 구성도

```
사용자
  ↓
Route 53 (도메인)
  ↓
Nginx (Virtual Host - 도메인별 분기)
  ├── review.domain.com  → REVIEW (Laravel)
  ├── crew.domain.com    → CREW (Laravel)
  └── api.domain.com     → CORE (FastAPI)
        ↓
      Supabase PostgreSQL
        ↓
      S3 (이미지 저장)
        ↓
      CloudFront (이미지 CDN)
```

---

## GitHub 레파지토리

```
(계정)/review-site/   → REVIEW
(계정)/running-crew/  → CREW
(계정)/core-api/      → CORE
```

---

## 미정 / 추후 논의 항목

- [ ] 프론트 프레임워크 (Blade 그대로 / Vue.js / React)
- [x] REVIEW / CREW 회원 통합 → 통합 방향 확정
- [ ] 도메인명 확정
- [ ] CI/CD 자동 배포 (GitHub Actions)
- [ ] Apify 비용 범위 확정
- [ ] 마라톤 대회 데이터 수집 방법 (수동입력 or 크롤링)
- [ ] SMS 인증 서비스 선택 (최후 수단 / 미정)
- [ ] SES 샌드박스 → 프로덕션 전환 시점
