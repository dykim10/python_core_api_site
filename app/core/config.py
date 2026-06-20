"""
환경 변수 설정 (app/core/config.py)

pydantic-settings 의 BaseSettings 를 사용해 .env 파일과 OS 환경 변수를 자동으로 읽는다.
모듈 하단의 settings 싱글턴을 다른 모듈에서 import 해서 사용한다.

  from app.core.config import settings
  print(settings.supabase_url)

[주요 환경 변수]
  SUPABASE_URL / SUPABASE_KEY           : Supabase anon 접속 정보
  SUPABASE_SERVICE_ROLE_KEY             : RLS 우회용 서비스 롤 키 (서버 사이드 전용)
  OPENAI_API_KEY                        : GPT-4o 이미지 파싱 / 리뷰 요약용
  ANTHROPIC_API_KEY                     : Claude API (향후 전환 예정)
  AWS_ACCESS_KEY_ID / SECRET_ACCESS_KEY : S3 업로드용
  AWS_BUCKET                            : 러닝 이미지 저장 버킷 이름
  ENCRYPT_KEY                           : Fernet AES-128 암호화 키 (개인정보 보호)
  APP_ENV                               : development / production — Swagger UI 활성화 제어
  APIFY_API_KEY                         : Apify REST API 키 (YouTube / Instagram 크롤링)

extra = "ignore" 로 .env 에 선언되지 않은 키가 있어도 오류 없이 무시한다.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── 로컬(테스트) Supabase ──────────────────────────────────────────────────
    supabase_url: str
    supabase_key: str
    supabase_service_role_key: str = ""

    # ── 실서버(LIVE) Supabase ─────────────────────────────────────────────────
    supabase_live_url: str = ""
    supabase_live_service_role_key: str = ""

    # ── AI ───────────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # ── 기상청 API Hub ────────────────────────────────────────────────────────
    kma_api_key: str = ""
    kma_api_base: str = "https://apihub.kma.go.kr/api/typ01/url"

    # ── AWS ──────────────────────────────────────────────────────────────────
    app_env: str = "development"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_default_region: str = "ap-northeast-2"
    aws_bucket: str = ""
    aws_url: str = ""  # CloudFront URL

    # ── 기타 ─────────────────────────────────────────────────────────────────
    encrypt_key: str = ""
    solapi_api_key: str = ""
    solapi_api_secret: str = ""
    sms_sender: str = ""
    apify_api_key: str = ""
    backup_api_key: str = ""
    backup_retention_days: int = 7

    # ── 이메일 (Resend) ───────────────────────────────────────────────────────
    resend_api_key: str = ""
    mail_from_address: str = "noreply@pac-run.com"
    mail_from_name: str = "PAC-RUN"
    mailing_test_email: str = ""  # 설정 시 서버 시작 90분 후 테스트 발송

    # World Athletics GraphQL (Next.js 클라이언트 공개 키 — env로 override 가능)
    wa_graphql_api_key: str = "da2-jkcja3ykujbf3cz64fs7w5gl6m"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
