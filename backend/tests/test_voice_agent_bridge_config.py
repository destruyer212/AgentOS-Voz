from app.agents.state import OrderLineDraft, get_or_create, reset
from app.infrastructure.config import settings
from app.integrations.voice_agent_bridge import (
    _GREETING,
    _LISTEN_KEYTERMS,
    _build_settings,
    _greeting_for,
    is_voice_agent_bridge_ready,
    missing_voice_agent_bridge_settings,
)


def _snapshot_settings() -> tuple[bool, bool, str | None, str | None]:
    return (
        settings.voice_agent_bridge_enabled,
        settings.media_streaming_enabled,
        settings.public_base_url,
        settings.deepgram_api_key,
    )


def _restore_settings(snapshot: tuple[bool, bool, str | None, str | None]) -> None:
    (
        settings.voice_agent_bridge_enabled,
        settings.media_streaming_enabled,
        settings.public_base_url,
        settings.deepgram_api_key,
    ) = snapshot


def test_voice_agent_bridge_is_not_ready_when_required_settings_are_missing():
    snapshot = _snapshot_settings()
    try:
        settings.voice_agent_bridge_enabled = True
        settings.media_streaming_enabled = True
        settings.public_base_url = None
        settings.deepgram_api_key = None

        assert not is_voice_agent_bridge_ready()
        assert missing_voice_agent_bridge_settings() == ["PUBLIC_BASE_URL", "DEEPGRAM_API_KEY"]
    finally:
        _restore_settings(snapshot)


def test_voice_agent_bridge_settings_encode_customer_phone_in_proxy_url():
    snapshot = _snapshot_settings()
    try:
        settings.voice_agent_bridge_enabled = True
        settings.media_streaming_enabled = True
        settings.public_base_url = "https://agentos.example.com"
        settings.deepgram_api_key = "test-key"

        assert is_voice_agent_bridge_ready()
        bridge_settings = _build_settings("call-123", "+51987654321")
        proxy_url = bridge_settings["agent"]["think"]["endpoint"]["url"]

        assert proxy_url.startswith(
            "https://agentos.example.com/api/v1/agent-llm-proxy/call-123/chat/completions"
        )
        assert "customer_phone=%2B51987654321" in proxy_url
    finally:
        _restore_settings(snapshot)


def test_settings_send_keyterms_to_boost_menu_vocabulary():
    # Palabras del menu que ya generaron un pedido mal entendido en una
    # llamada real ("Mostro" -> "monstruo", "Yape" -> "yate", "Plin" ->
    # "pli", "Chaufa" -> "Chaupa") deben ir en listen.provider.keyterms
    # -- ver https://developers.deepgram.com/docs/keyterm.
    snapshot = _snapshot_settings()
    try:
        settings.voice_agent_bridge_enabled = True
        settings.media_streaming_enabled = True
        settings.public_base_url = "https://agentos.example.com"
        settings.deepgram_api_key = "test-key"

        bridge_settings = _build_settings("call-123", "+51987654321")
        keyterms = bridge_settings["agent"]["listen"]["provider"]["keyterms"]

        assert keyterms is _LISTEN_KEYTERMS
        for expected in ("Mostro", "Yape", "Plin", "Chaufa", "Olivar"):
            assert expected in keyterms
    finally:
        _restore_settings(snapshot)


def test_greeting_is_the_default_for_a_call_with_no_prior_state():
    assert _greeting_for("call-sin-historial-todavia") == _GREETING


def test_greeting_resumes_instead_of_restarting_when_state_already_has_items():
    # Bug real, visto en vivo: Telnyx reconecto el stream de audio a mitad
    # de una llamada (el call_control_id no cambio) y Deepgram, al ser una
    # conexion nueva, repitio el saludo de siempre -- sonaba como que el
    # pedido en curso se habia perdido, aunque en realidad seguia intacto
    # en el ConversationState de esa llamada.
    call_control_id = "call-reconectado-a-mitad-de-pedido"
    try:
        state = get_or_create(call_control_id, settings.default_tenant_id)
        state.items.append(
            OrderLineDraft(product_id=1, name="Hamburguesa Clasica", quantity=1, unit_price=12.9)
        )

        greeting = _greeting_for(call_control_id)

        assert greeting != _GREETING
        assert "Hamburguesa Clasica" in greeting
    finally:
        reset(call_control_id)
