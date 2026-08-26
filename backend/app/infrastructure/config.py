from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AgentOS Voz API"
    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./agentos.db"
    default_tenant_id: str = "tenant_demo"
    llm_provider: str = "rule_based"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # Telefonia (Sprint 7). Account SID + Auth Token alcanzan para toda la
    # REST API (comprar numero, TwiML, llamadas salientes); no hace falta
    # una API Key/Secret separada para esto.
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_phone_number: str | None = None
    twilio_verify_signature: bool = False

    # Telnyx: alternativa a Twilio, mismo runtime del agente por debajo.
    telnyx_api_key: str | None = None
    telnyx_dry_run: bool = False

    agent_voice_language: str = "es-MX"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
