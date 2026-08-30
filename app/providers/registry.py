"""Складання провайдерів за конфігом простору.

Ядро отримує готовий обʼєкт і не знає, кого саме дістали з реєстру.
"""

from typing import Any, Dict

import os

from .base import LLMProvider, ProviderError, TTSProvider


def build_llm(cfg: Dict[str, Any]) -> LLMProvider:
    # На Vercel локальні провайдери (mlx) фізично не запускаються — окрема
    # env-змінна дає задеплоєному оточенню свій провайдер БЕЗ дублювання
    # space.json: той самий гайд лишається джерелом істини і локально, і в
    # хмарі, лише LLM/TTS під капотом різні.
    provider = os.environ.get("LLM_PROVIDER_OVERRIDE") or (cfg or {}).get("provider", "mock")
    if provider == "mock":
        from .llm_mock import MockLLM

        return MockLLM()
    if provider == "mock_bad":
        # Заглушка, що свідомо порушує правила — щоб побачити guard у роботі.
        from .llm_mock import MockLLM

        return MockLLM(misbehave=True)
    if provider == "mlx":
        from .llm_mlx import DEFAULT_MODEL as MLX_DEFAULT, MlxLLM

        return MlxLLM(model_path=cfg.get("model") or MLX_DEFAULT,
                      max_tokens=int(cfg.get("max_tokens", 80)))

    if provider == "anthropic":
        from .llm_anthropic import AnthropicLLM, DEFAULT_MODEL

        return AnthropicLLM(model=cfg.get("model", DEFAULT_MODEL))
    raise ProviderError(
        "Невідомий LLM-провайдер '%s'. Доступні: mock, mock_bad, mlx, anthropic." % provider
    )


def build_tts(cfg: Dict[str, Any]) -> Any:
    """Повертає провайдера озвучення або None, якщо озвучення на боці браузера.

    "browser" — не провайдер: синтез робить сам браузер респондента, серверу
    робити нічого. Тому None, а не заглушка.
    """
    # Той самий принцип, що й у build_llm: env-змінна дає задеплоєному
    # оточенню свій провайдер, не чіпаючи space.json.
    provider = os.environ.get("TTS_PROVIDER_OVERRIDE") or (cfg or {}).get("provider", "none")
    if provider in ("none", "browser", None):
        return None

    if provider == "say":
        from .tts_say import SayTTS

        return SayTTS(voice=cfg.get("voice"), rate_wpm=cfg.get("rate_wpm"))

    if provider == "piper":
        from .tts_piper import PiperTTS

        # На відміну від espnet/mlx, ця модель (73 МБ, без torch) достатньо
        # легка, щоб піти прямо в git і в Vercel-бандл — тому шлях за
        # замовчуванням береться від кореня проєкту, а не лише з local/.
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        default_model = os.path.join(root, "voices", "piper", "uk_UA-ukrainian_tts-medium.onnx")
        return PiperTTS(
            model_path=cfg.get("model_path") or os.environ.get("PIPER_MODEL") or default_model,
            voice=cfg.get("voice"),
            length_scale=cfg.get("length_scale"),
            sentence_silence=cfg.get("sentence_silence"),
            noise_scale=cfg.get("noise_scale"),
            noise_w_scale=cfg.get("noise_w_scale"),
            add_stress=cfg.get("add_stress", True),
        )

    if provider == "espnet":
        from .tts_espnet import EspnetTTS

        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return EspnetTTS(
            python_path=cfg.get("python_path") or os.path.join(root, ".venv-espnet", "bin", "python"),
            worker_path=cfg.get("worker_path") or os.path.join(root, "local", "bin", "espnet_worker.py"),
            cache_folder=cfg.get("model_cache") or os.path.join(root, "local", "models", "espnet-cache"),
            audio_cache=cfg.get("audio_cache") or os.path.join(root, "local", "data", "tts-cache"),
            voice=cfg.get("voice"),
            stress=cfg.get("stress", "dictionary"),
        )

    if provider == "azure":
        from .tts_azure import AzureTTS

        # Ключ — тільки із середовища. У конфізі простору його бути не має:
        # простори лежать у репозиторії поруч із макетами.
        return AzureTTS(
            api_key=os.environ.get("AZURE_SPEECH_KEY", ""),
            region=cfg.get("region") or os.environ.get("AZURE_SPEECH_REGION", ""),
            voice=cfg.get("voice"),
            lang=cfg.get("lang", "uk-UA"),
            rate=cfg.get("rate_ssml"),
            pitch=cfg.get("pitch_ssml"),
        )

    raise ProviderError(
        "Невідомий TTS-провайдер '%s'. Доступні: browser, say, piper, espnet, azure." % provider
    )
