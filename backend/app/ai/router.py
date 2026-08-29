import logging

from app.ai.base import LLMProvider
from app.ai.rule_based import RuleBasedProvider
from app.infrastructure.config import settings

logger = logging.getLogger(__name__)


class AIRouter:
    """Selecciona el proveedor de IA activo segun configuracion. Los
    proveedores reales (Gemini/Ollama) se agregan aqui sin tocar al agente."""

    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {
            "rule_based": RuleBasedProvider(),
        }

    def get_provider(self) -> LLMProvider:
        if settings.llm_provider not in self._providers:
            try:
                self._providers[settings.llm_provider] = self._build(settings.llm_provider)
            except Exception:
                logger.exception(
                    "No se pudo activar LLM_PROVIDER=%s; usando rule_based como fallback.",
                    settings.llm_provider,
                )
                self._providers[settings.llm_provider] = self._providers["rule_based"]
                return self._providers["rule_based"]
        return self._providers[settings.llm_provider]

    def _build(self, name: str) -> LLMProvider:
        if name == "gemini":
            from app.ai.gemini import (
                GeminiProvider,  # import perezoso: no exige el SDK si no se usa
            )

            return GeminiProvider()
        raise NotImplementedError(f"Proveedor de IA no soportado todavia: {name}")


ai_router = AIRouter()
