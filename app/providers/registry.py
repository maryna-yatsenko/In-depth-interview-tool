"""Складання провайдерів за конфігом простору.

Ядро отримує готовий обʼєкт і не знає, кого саме дістали з реєстру.
"""

from typing import Any, Dict

import os

from .base import LLMProvider, ProviderError


def build_llm(cfg: Dict[str, Any]) -> LLMProvider:
    # На Vercel локальний провайдер (mlx) фізично не запускається — окрема
    # env-змінна дає задеплоєному оточенню свій провайдер БЕЗ дублювання
    # space.json: той самий гайд лишається джерелом істини і локально, і в
    # хмарі, лише LLM під капотом різний.
    provider = os.environ.get("LLM_PROVIDER_OVERRIDE") or (cfg or {}).get("provider", "mock")
    if provider == "mock":
        from .llm_mock import MockLLM

        return MockLLM()
    if provider == "mlx":
        from .llm_mlx import DEFAULT_MODEL as MLX_DEFAULT, MlxLLM

        return MlxLLM(model_path=cfg.get("model") or MLX_DEFAULT,
                      max_tokens=int(cfg.get("max_tokens", 80)))

    if provider == "anthropic":
        from .llm_anthropic import AnthropicLLM, DEFAULT_MODEL

        return AnthropicLLM(model=cfg.get("model", DEFAULT_MODEL))
    raise ProviderError(
        "Невідомий LLM-провайдер '%s'. Доступні: mock, mlx, anthropic." % provider
    )
