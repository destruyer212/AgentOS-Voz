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
    # Cobro fijo del motorizado quando el pedido es delivery (nunca en
    # recojo en el local). Unica fuente de verdad: tambien es el precio del
    # producto "Delivery" real en el catalogo (ver
    # scripts/ensure_delivery_fee_product.py) -- se mantienen sincronizados
    # a mano, no hay una relacion de FK que lo garantice solo.
    delivery_fee_soles: float = 10.0
    # Tiempo estimado que se le dice al cliente por WhatsApp cuando el
    # pedido sale con el motorizado (ver app/integrations/wsp_notifications.py,
    # notify_order_dispatched). Texto libre a proposito -- se manda tal cual
    # dentro del mensaje ("Llegada estimada: <esto>").
    delivery_eta_label: str = "30 min"
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

    # Corte de llamadas colgadas/con ruido de fondo (ver
    # app/integrations/voice_agent_bridge.py, silence_and_duration_watchdog):
    # Telnyx cobra por minuto sin importar si hay una conversacion real
    # pasando, asi que una llamada que nadie corta (el cliente se olvida, o
    # hay gente hablando cerca del telefono sin pedir nada) sigue generando
    # costo indefinidamente si no se corta sola. Dos mecanismos, pensados
    # para no confundirse entre si:
    #   1. Silencio real (nadie dice nada que llegue a completar un turno
    #      -- ver ConversationState.last_touched_at): a los
    #      call_silence_warning_seconds sin actividad se avisa una vez
    #      ("¿sigues ahi?"); si sigue sin actividad
    #      call_silence_hangup_grace_seconds mas, se cuelga.
    #   2. Duracion maxima dura: sin importar cuanta "actividad" haya (ruido
    #      de fondo transcrito de casualidad, gente hablando sin pedir
    #      nada), ninguna llamada dura mas de call_max_duration_seconds --
    #      un pedido real de restaurante nunca se acerca a este limite, es
    #      la red de seguridad de costo definitiva.
    call_silence_warning_seconds: int = 35
    call_silence_hangup_grace_seconds: int = 15
    call_max_duration_seconds: int = 600

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

    # wsp-service: microservicio Baileys separado (repo y despliegue propio,
    # cuenta AWS distinta -- ver C:\whatsapp-service\DEPLOYMENT.md) que manda
    # la confirmacion de pedido por WhatsApp real. Opcional a proposito: si
    # cualquiera de las dos queda vacia, el envio se salta en silencio (ver
    # app/integrations/wsp_notifications.py) -- nunca debe poder tumbar una
    # llamada real por un problema de config o de WhatsApp.
    wsp_service_url: str | None = None
    wsp_service_api_key: str | None = None

    # api.apiperu.pe: consulta real de DNI/RUC (ver
    # app/integrations/apiperu_client.py) para poner el nombre completo
    # (RENIEC) o la razon social (SUNAT) REALES en la boleta/factura, en
    # vez de lo que el cliente alcanza a decir por telefono. Opcional a
    # proposito -- sin token, agents/runtime.py sigue con su fallback de
    # siempre (el nombre que dio el cliente / "CLIENTE"), nunca bloquea
    # una llamada real.
    apiperu_token: str | None = None

    # Carrito visual durante la llamada (ver
    # docs/08-mejora-carrito-visual-en-llamada.md,
    # app/domain/order_review.py) -- feature nueva y AISLADA a proposito:
    # si no funciona bien, se borra entera (este modulo + su router +
    # order_review.py + la pagina /revisar en el frontend) sin tocar nada
    # mas del sistema. `order_review_secret` firma el token temporal del
    # link; sin configurar usa un default de desarrollo (cambiar en
    # produccion). `frontend_public_url` es donde vive la pagina publica
    # (Vercel), para armar el link real que se manda por WhatsApp.
    order_review_secret: str | None = None
    frontend_public_url: str = "https://agent-os-voz.vercel.app"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
