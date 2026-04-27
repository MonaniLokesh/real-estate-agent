from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "EstateAgent AI"
    app_version: str = "0.2.0"

    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_temperature: float = 0

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    # Optional direct Postgres URL (e.g. Supabase "Connection string" URI) for agent SQL reads.
    # database_url: str = ""
    # Optional pooler URL; preferred fallback for containerized environments.
    supabase_db_url: str = ""

    whatsapp_webhook_secret: str = ""
    allow_debug: bool = False

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
