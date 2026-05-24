"""
데이터베이스 연결 (app/core/database.py)

Supabase Python SDK 를 통해 PostgreSQL 에 접속한다.
모듈 레벨 변수(_client, _service_client)로 클라이언트를 한 번만 생성하고 재사용한다.
(싱글턴 패턴 — 매 요청마다 새 커넥션을 열지 않음)

[클라이언트 종류]
  get_supabase()          : anon 키 — Supabase RLS 정책 적용
  get_service_supabase()  : service_role 키 — RLS 완전 우회, 서버 사이드 전용

[스키마별 편의 함수] — 라우터에서 직접 호출
  public_db() → public 스키마  (users, crews, branches, groups)
  review_db() → review 스키마  (races, reviews, race_weather)
  crew_db()   → crew   스키마  (running_logs, events, event_scores, user_goals)

  세 함수 모두 service_role 키를 사용해 RLS 없이 전체 데이터에 접근한다.
  .schema("review") / .schema("crew") 로 스키마를 전환한다.
"""
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
