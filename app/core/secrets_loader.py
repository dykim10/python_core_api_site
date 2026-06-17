import os

from dotenv import load_dotenv

REGION = "ap-northeast-2"
PATH_PREFIX = "/pac-run/prod/"

# 경로(접두사 제거 후) → 실제 환경변수 이름. 자동 대문자화 변환 금지 —
# supabase/db-password 가 SUPABASE_DB_PASSWORD 로 잘못 매핑되는 것을 방지한다.
PARAM_MAP = {
    "supabase/service-role-key": "SUPABASE_SERVICE_ROLE_KEY",
    "supabase/db-password": "DB_PASSWORD",
    "security/encrypt-key": "ENCRYPT_KEY",
    "anthropic/api-key": "ANTHROPIC_API_KEY",
    "openai/api-key": "OPENAI_API_KEY",
    "solapi/api-key": "SOLAPI_API_KEY",
    "solapi/api-secret": "SOLAPI_API_SECRET",
    "sms/webhook-secret": "SMS_WEBHOOK_SECRET",
    "resend/api-key": "RESEND_API_KEY",
    "apify/api-key": "APIFY_API_KEY",
    "kma/api-key": "KMA_API_KEY",
}


def load_secrets() -> None:
    # pydantic-settings 는 .env 값을 Settings 필드에만 채우고 os.environ 에는 반영하지
    # 않는다. 이 함수는 Settings 생성 전에 실행되므로, APP_ENV 가 systemd 등에서 실제
    # OS 환경변수로 export 되어 있지 않다면 .env 의 APP_ENV 를 읽기 위해 load_dotenv 가
    # 필요하다. override=False 라 실제 OS 환경변수가 있으면 그게 우선한다.
    load_dotenv(override=False)

    if os.getenv("APP_ENV") != "production":
        return  # 로컬 등: Parameter Store 호출 없이 .env 그대로 사용

    import boto3  # 로컬에 boto3가 없어도 영향 없도록 함수 내부 import

    ssm = boto3.client("ssm", region_name=REGION)
    paginator = ssm.get_paginator("get_parameters_by_path")

    loaded = 0
    for page in paginator.paginate(
        Path=PATH_PREFIX,
        Recursive=True,
        WithDecryption=True,
    ):
        for p in page["Parameters"]:
            key = p["Name"][len(PATH_PREFIX):]
            env_name = PARAM_MAP.get(key)
            if env_name:
                os.environ[env_name] = p["Value"]
                loaded += 1

    # uvicorn이 logging 초기화 전에 호출되므로 logger.info 가 dropped됨 → print 사용
    print(f"[secrets] Parameter Store에서 {loaded}개 비밀 로드 완료", flush=True)
