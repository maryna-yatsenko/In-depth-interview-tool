"""LLM-провайдер: Claude через офіційний SDK.

Не єдиний можливий — саме тому він за інтерфейсом LLMProvider. Заміна вендора
(наприклад на Claude через Microsoft Foundry для корпоративного контура) —
новий файл поруч, а не правки в ядрі.
"""

import json
from typing import Any, Dict, List

from .base import LLMProvider, ProviderError

DEFAULT_MODEL = "claude-opus-5"

# Моделі, які приймають system-повідомлення посеред розмови. Список звужений
# свідомо: Sonnet 5 цього не вміє, і тихий фолбек краще за 400 посеред інтервʼю.
_SYSTEM_TURN_MODELS = ("claude-opus-5", "claude-opus-4-8", "claude-fable-5", "claude-mythos-5")


class AnthropicLLM(LLMProvider):
    name = "anthropic"

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str = None):
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise ProviderError(
                "Не встановлений пакет anthropic. Постав: pip3 install anthropic"
            ) from exc
        import anthropic

        # Без api_key SDK сам візьме ANTHROPIC_API_KEY з середовища —
        # ключ не хардкодимо і в репозиторій не кладемо ніколи.
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self._anthropic = anthropic
        self.model = model
        self.supports_system_turns = model in _SYSTEM_TURN_MODELS

    def respond_json(
        self,
        system: str,
        messages: List[Dict[str, Any]],
        schema: Dict[str, Any],
        max_tokens: int = 2000,
    ) -> Dict[str, Any]:
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except self._anthropic.APIError as exc:
            raise ProviderError("LLM не відповів: %s" % exc) from exc

        # Модель могла відмовитись — це HTTP 200, а не виняток.
        if getattr(response, "stop_reason", None) == "refusal":
            raise ProviderError("LLM відмовився відповідати (stop_reason=refusal)")

        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            raise ProviderError("LLM повернув відповідь без тексту")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError("LLM повернув невалідний JSON: %s" % exc) from exc
