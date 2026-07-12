"""
CORE API — 진입점 (main.py)

FastAPI 애플리케이션을 생성하고 모든 라우터를 등록하는 최상위 파일.
uvicorn main:app --reload 명령으로 실행한다.

[Swagger / ReDoc]
  APP_ENV=development 일 때만 /docs, /redoc 활성화
  운영 환경에서는 docs_url=None 으로 자동 비활성화 (보안)

[등록된 라우터]
  users         → /api/users
  races         → /api/races
  running_logs  → /api/running-logs
  parse_image   → /api/parse-image
  race_info     → /api/race-info
  summarize     → /api/summarize
  race_summarize→ /api/races/summarize
  crypto        → /api/crypto
  participants  → /api/participants
  sms           → /api/sms
  s3            → /api/s3
  apify         → /api/apify/youtube, /api/instagram/posts, /api/instagram/fetch

[헬스체크 엔드포인트]
  GET /          → {"status": "ok", "env": "development|production"}
  GET /health    → {"status": "ok"} (프로세스 생존, DB 미조회 — CI/CD 헬스체크용)
  GET /health/db → public / review / crew 스키마 각 1건 조회 확인
                   실패 시 {"status": "error", "detail": "..."}
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# settings(app.core.config) 가 import 되기 전에 호출해야 Parameter Store 값이
# Settings 필드에 반영된다. import 순서를 절대 바꾸지 말 것.
from app.core.secrets_loader import load_secrets

load_secrets()

from app.core.config import settings
from app.core.database import public_db, review_db, crew_db
from app.api.routes import running_logs, users, races, parse_image, race_info, summarize, race_summarize, crypto, participants, sms, s3, apify, photo, backup, weather, email, mailing, gpx, rag, race_plan, sns, course, coach

try:
    from app.core import scheduler as sched
    _SCHEDULER_AVAILABLE = True
except ImportError:
    _SCHEDULER_AVAILABLE = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    if _SCHEDULER_AVAILABLE:
        sched.start()
    yield
    if _SCHEDULER_AVAILABLE:
        sched.stop()


app = FastAPI(
    title="CORE API",
    description="데이터 수집 / 분석 / 통계 / 스케줄링 전담 API",
    version="0.1.0",
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url="/redoc" if settings.app_env == "development" else None,
    lifespan=lifespan,
)

app.include_router(users.router)
app.include_router(races.router)
app.include_router(running_logs.router)
app.include_router(parse_image.router)
app.include_router(race_info.router)
app.include_router(summarize.router)
app.include_router(race_summarize.router)
app.include_router(crypto.router)
app.include_router(participants.router)
app.include_router(sms.router)
app.include_router(s3.router)
app.include_router(apify.router)
app.include_router(photo.router)
app.include_router(backup.router)
app.include_router(weather.router)
app.include_router(email.router)
app.include_router(mailing.router)
app.include_router(gpx.router)
app.include_router(course.router)
app.include_router(rag.router)
app.include_router(race_plan.router)
app.include_router(sns.router)
app.include_router(coach.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, (StarletteHTTPException, RequestValidationError)):
        raise exc
    from app.services.system_log_service import db_log
    db_log("app_error", "error", str(exc)[:500], {
        "path": str(request.url.path),
        "exception": type(exc).__name__,
    })
    return JSONResponse(status_code=500, content={"detail": "서버 오류가 발생했습니다."})


@app.get("/")
def health_check():
    return {"status": "ok", "env": settings.app_env}


@app.get("/health")
def health():
    """프로세스 생존 확인 — DB 등 외부 의존성 없음 (CI/CD·systemd용)."""
    return {"status": "ok"}


@app.get("/health/db")
def db_check():
    try:
        public_db().table("users").select("id").limit(1).execute()
        review_db().table("races").select("id").limit(1).execute()
        crew_db().table("running_logs").select("id").limit(1).execute()
        return {"status": "ok", "schemas": ["public", "review", "crew"]}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
