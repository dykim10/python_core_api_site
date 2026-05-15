from fastapi import FastAPI
from app.core.config import settings
from app.core.database import public_db, review_db, crew_db
from app.api.routes import running_logs, users, races

app = FastAPI(
    title="CORE API",
    description="데이터 수집 / 분석 / 통계 / 스케줄링 전담 API",
    version="0.1.0",
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url="/redoc" if settings.app_env == "development" else None,
)

app.include_router(users.router)
app.include_router(races.router)
app.include_router(running_logs.router)


@app.get("/")
def health_check():
    return {"status": "ok", "env": settings.app_env}


@app.get("/health/db")
def db_check():
    try:
        public_db().table("users").select("id").limit(1).execute()
        review_db().table("races").select("id").limit(1).execute()
        crew_db().table("running_logs").select("id").limit(1).execute()
        return {"status": "ok", "schemas": ["public", "review", "crew"]}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
