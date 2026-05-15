from supabase import create_client, Client
from app.core.config import settings

_client: Client | None = None
_service_client: Client | None = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        _client = create_client(settings.supabase_url, settings.supabase_key)
    return _client


def get_service_supabase() -> Client:
    """RLS 우회가 필요한 서버 사이드 작업용 (service_role 키)"""
    global _service_client
    if _service_client is None:
        _service_client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    return _service_client


def public_db():
    """public 스키마 (users, crews, branches, groups)"""
    return get_service_supabase()


def review_db():
    """review 스키마 (races, reviews, race_weather)"""
    return get_service_supabase().schema("review")


def crew_db():
    """crew 스키마 (running_logs, events, event_scores, user_goals)"""
    return get_service_supabase().schema("crew")
