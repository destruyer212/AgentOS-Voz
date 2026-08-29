from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AgentOS Voz API"
    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./agentos.db"
    default_tenant_id: str = "tenant_demo"
    # Nombre del restaurante que el agente dice en el saludo (telefono y
    # web). Configurable por .env para no tener que tocar codigo cuando
    # cambie el negocio -- ver voice_agent_bridge.py y agents/runtime.py.
    restaurant_name: str = "El Olivar Grill"
    # Horario real de atencion (ver app/domain/business_hours.py): todos los
    # dias de 12:00 a 23:00 segun la carta publicada. Formato 24h "HH:MM".
    business_hours_open: str = "12:00"
    business_hours_close: str = "23:00"
    business_timezone: str = "America/Lima"
    llm_provider: str = "rule_based"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_fast_path_enabled: bool = True
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

    # Voice Engine V2 (Sprint de streaming): Fase 1 -- solo escucha el audio
    # crudo de Media Streaming en paralelo al flujo actual (Call Control),
    # sin todavia manejar la conversacion. Apagado por default a proposito:
    # el numero real sigue funcionando exactamente igual hasta que se prenda
    # explicitamente para probar. `public_base_url` es la URL publica actual
    # del tunel (cambia cada vez que se reinicia cloudflared, igual que el
    # webhook de Telnyx -- ver scripts/setup_telnyx.py).
    media_streaming_enabled: bool = False
    public_base_url: str | None = None
    deepgram_api_key: str | None = None
    # Fase 3+: cuando esta prendido, Deepgram Voice Agent toma el control
    # TOTAL de la conversacion (STT+think+TTS+barge-in) sobre el audio de
    # Media Streaming, y el flujo viejo de Call Control (saludo/speak/
    # transcription_start manual) se salta por completo para esa llamada --
    # nunca deben correr los dos a la vez, sonarian dos agentes encima uno
    # del otro. Requiere media_streaming_enabled=true tambien.
    voice_agent_bridge_enabled: bool = False

    # Bug real (ago 2026): conversaciones de canal web abandonadas a mitad
    # de flujo (el usuario cierra la pestana, o son pruebas manuales via
    # /agent/turn) se quedaban en status="active" para siempre -- el chat
    # web no tiene equivalente al hangup de la llamada telefonica. Un
    # barrido periodico las cierra solo si no tuvieron actividad en
    # `stale_conversation_timeout_minutes`. Nunca toca canal "phone": esas
    # ya se cierran solas via el bridge de Telnyx/Deepgram (ver
    # voice_agent_bridge.py) y forzar un cierre aca podria cortar una
    # llamada real en curso.
    stale_conversation_timeout_minutes: int = 20
    stale_conversation_sweep_interval_seconds: int = 300

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
