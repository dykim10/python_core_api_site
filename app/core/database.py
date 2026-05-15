from supabase import create_client, Client
from app.core.config import settings

_client: Client | None = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        _client = create_client(settings.supabase_url, settings.supabase_key)
    return _client


def public_db():
    """public 스키마 (users, crews, branches, groups)"""
    return get_supabase()


def review_db():
    """review 스키마 (races, reviews, race_weather)"""
    return get_supabase().schema("review")


def crew_db():
    """crew 스키마 (running_logs, events, event_scores, user_goals)"""
    return get_supabase().schema("crew")
