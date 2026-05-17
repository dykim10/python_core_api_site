from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_key: str
    supabase_service_role_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    app_env: str = "development"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_default_region: str = "ap-northeast-2"
    aws_bucket: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
