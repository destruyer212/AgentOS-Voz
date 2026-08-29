import pytest

from app.ai.base import ParsedMessage
from app.ai.gemini import GeminiProvider
from app.infrastructure.config import settings


@pytest.fixture(autouse=True)
def gemini_test_settings():
    previous_api_key = settings.gemini_api_key
    previous_fast_path = settings.gemini_fast_path_enabled
    settings.gemini_api_key = "test-key"
    settings.gemini_fast_path_enabled = True
    yield
    settings.gemini_api_key = previous_api_key
    settings.gemini_fast_path_enabled = previous_fast_path


@pytest.mark.asyncio
async def test_gemini_fast_path_skips_network_for_obvious_order(monkeypatch):
    provider = GeminiProvider()

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("Gemini no debio ser llamado para un pedido obvio.")

    monkeypatch.setattr(provider, "_parse_with_gemini", fail_if_called)

    parsed = await provider.parse_message(
        "Quiero una hamburguesa clasica y una Inca Kola",
        awaiting_confirmation=False,
    )

    assert parsed.intent == "order.create"
    assert [item.query for item in parsed.items] == ["hamburguesa clasica", "Inca Kola"]
    assert getattr(parsed, "used_fast_path", False) is True


@pytest.mark.asyncio
async def test_gemini_fast_path_skips_network_for_confirmation(monkeypatch):
    provider = GeminiProvider()

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("Gemini no debio ser llamado para una confirmacion obvia.")

    monkeypatch.setattr(provider, "_parse_with_gemini", fail_if_called)

    parsed = await provider.parse_message("si, confirmo", awaiting_confirmation=True)

    assert parsed.intent == "order.confirm"
    assert parsed.confirms is True
    assert getattr(parsed, "used_fast_path", False) is True


@pytest.mark.asyncio
async def test_gemini_fast_path_defers_to_gemini_for_price_question(monkeypatch):
    provider = GeminiProvider()

    async def fake_gemini(*args, **kwargs):
        return ParsedMessage(intent="menu.inquiry")

    monkeypatch.setattr(provider, "_parse_with_gemini", fake_gemini)

    parsed = await provider.parse_message(
        "Quiero saber el precio de la hamburguesa clasica",
        awaiting_confirmation=False,
    )

    assert parsed.intent == "menu.inquiry"
    assert getattr(parsed, "used_fast_path", False) is False
