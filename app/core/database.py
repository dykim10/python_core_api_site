"""
데이터베이스 연결 (app/core/database.py)

Supabase Python SDK 를 통해 PostgreSQL 에 접속한다.

[DB 구분]
  로컬(테스트) : SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY
  실서버(LIVE)  : SUPABASE_LIVE_URL + SUPABASE_LIVE_SERVICE_ROLE_KEY

[스키마별 편의 함수]
  public_db(live)  → public 스키마
  review_db(live)  → review 스키마  (races, reviews, race_weather, weather_stations)
  crew_db(live)    → crew   스키마

  live=False (기본) → 로컬 테스트 DB
  live=True         → 실서버 DB
"""
from supabase import create_client, Client
from app.core.config import settings

_local_client: Client | None = None
_live_client:  Client | None = None


def _local() -> Client:
    global _local_client
    if _local_client is None:
        _local_client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )
    return _local_client


def _live() -> Client:
    global _live_client
    if _live_client is None:
        if not settings.supabase_live_url or not settings.supabase_live_service_role_key:
            raise ValueError("SUPABASE_LIVE_URL / SUPABASE_LIVE_SERVICE_ROLE_KEY 가 .env 에 없습니다.")
        _live_client = create_client(
            settings.supabase_live_url,
            settings.supabase_live_service_role_key,
        )
    return _live_client


def _client(live: bool = False) -> Client:
    return _live() if live else _local()


# ── 하위 호환 (기존 코드에서 인수 없이 호출) ─────────────────────────────────
def get_supabase() -> Client:
    return _local()


def get_service_supabase() -> Client:
    return _local()


# ── 스키마 편의 함수 ─────────────────────────────────────────────────────────
def public_db(live: bool = False):
    """public 스키마 (users, crews, branches, groups)"""
    return _client(live)


def review_db(live: bool = False):
    """review 스키마 (races, reviews, race_weather, weather_stations)"""
    return _client(live).schema("review")


def crew_db(live: bool = False):
    """crew 스키마 (running_logs, events, event_scores, user_goals)"""
    return _client(live).schema("crew")
