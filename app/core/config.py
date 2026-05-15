from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_key: str
    supabase_service_role_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    app_env: str = "development"

    class Config:
        env_file = ".env"


settings = Settings()
