# CORE 프로젝트 - Claude Code 지침

> AI 분석 / 크롤링 전담 Python FastAPI 서버  
> **스펙 정본:** `../../.claude/definition/08-core.md` · **진행:** `../../developer_md/STATUS.md`  
> `./project-definition.md` · `../project-definition.md`는 **레거시** — 갱신하지 않는다.

@../../developer_md/STATUS.md
@../../.claude/definition/01-overview.md
@../../.claude/definition/02-common-rules.md
@../../.claude/definition/04-api-endpoints.md
@../../.claude/definition/08-core.md
@../../.claude/definition/09-infra-ops.md

---

## 문서 자동 갱신 (doc-sync)

새 API·서비스 완료·commit 직전·`/compact` 직전·"문서 갱신" 요청 시:

1. **`../../.claude/definition/08-core.md`** — CORE 스펙·엔드포인트·완료/미완
2. **`../../.claude/definition/04-api-endpoints.md`** — API 표 (변경 시)
3. **`../../developer_md/STATUS.md`** — PLAN/TASK 진행만
4. 스케줄러 변경 시 **`09-infra-ops.md`**

상세 절차: 워크스페이스 루트 `.claude/skills/doc-sync.md` 또는 `/doc-sync`

---

## 기술 스택

| 구분 | 기술 |
|---|---|
| 언어 | Python 3.14 |
| 프레임워크 | FastAPI |
| DB | Supabase PostgreSQL |
| AI | Claude API (Vision · 요약 · race_plan) |
| 스케줄 | APScheduler |
| 기타 | boto3 · BeautifulSoup · Apify |

---

## 경로

| | |
|---|---|
| EC2 | `/var/www/fastapi/` |
| 로컬 | `C:\src\projects\core-api\` · 포트 **8100** |
| GitHub | https://github.com/dykim10/python_core_api_site.git |
| 운영 | https://api.pac-run.com (Swagger 비활성) |

---

## 호출 관계

```
REVIEW → CORE : summarize · GPX · race-plan · weather · SNS ...
CREW   → CORE : parse-image · SMS · S3 ...
```

엔드포인트 전체·모델 티어링·배치는 import된 **`08-core.md`** · **`04-api-endpoints.md`** 참조.

---

## 주의사항

- API Key / AWS 자격증명 — `.env` 또는 Parameter Store · Git 커밋 금지
- 운영 Swagger 비활성화
- Apify·Claude 비용 모니터링
- REVIEW는 `crew` 스키마 직접 JOIN 금지 — CORE 내부 cross-schema만 허용 범위는 definition 참조
