"""Локальна модель через MLX (Apple Silicon).

Навіщо: нуль коштів назавжди, без акаунта, і **дані не покидають машину** — для
транскриптів живих респондентів це вагоміше за зручність.

Ціна названа прямо (заміряно на M4/16 ГБ, gemma-3-4b-it-4bit):

- повний промпт `interviewer.v1` (~2600 токенів) → **6,5 с** на репліку;
- скорочений `interviewer.compact` (~310 токенів) → **1,2 с** при тих самих
  по суті питаннях.

Тому для локальних моделей типовий промпт — скорочений, і це фіксується в
транскрипті полем `prompt_version`.

Дві особливості, через які цей провайдер не може вдавати з себе Claude:

1. **Немає системної ролі й потрібне строге чергування user/assistant** — шаблон
   Gemma інакше падає. Тому системний промпт іде першою реплікою користувача, а
   службовий стан доклеюється до останньої.
2. **Структурованого виводу немає.** Просити JSON у 4B-моделі — це лотерея: у
   перевірці вона його просто проігнорувала. Тому провайдер віддає **текст
   питання**, а рішення про переходи ухвалює ядро своїми правилами — воно й так
   форсує ліміти уточнень і покриття тем.
"""

import re
import threading
from typing import Any, Dict, List, Optional

from .base import LLMProvider, ProviderError

DEFAULT_MODEL = "mlx-community/gemma-3-4b-it-4bit"


class MlxLLM(LLMProvider):
    name = "mlx"
    supports_system_turns = False
    # Ядро запитає текст, а не JSON, і саме визначить дію.
    supports_structured = False

    def __init__(self, model_path: str = DEFAULT_MODEL, max_tokens: int = 80):
        try:
            from mlx_lm import generate, load
        except ImportError as exc:
            raise ProviderError(
                "Немає mlx-lm. Постав: .venv/bin/pip install mlx-lm"
            ) from exc

        self._generate = generate
        self.model_path = model_path
        self.max_tokens = max_tokens
        # Генерація — під замком. Сервер багатопотоковий, а стан моделі спільний:
        # два одночасні запити (а вони бувають — жива перевірка чекліста йде
        # паралельно з відповіддю) псували б один одному генерацію.
        self._lock = threading.Lock()
        try:
            self._model, self._tokenizer = load(model_path)
        except Exception as exc:
            raise ProviderError("Не вдалося завантажити модель '%s': %s" % (model_path, exc))

    # ── допоміжне ────────────────────────────────────────────────────────

    @staticmethod
    def _alternate(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Зводить розмову до строгого чергування user/assistant.

        Шаблон Gemma інакше падає з `Conversation roles must alternate`.
        Сусідні репліки однієї ролі зливаються — зміст не губиться.
        """
        merged = []
        for message in messages:
            role = "assistant" if message["role"] == "assistant" else "user"
            content = message["content"]
            if merged and merged[-1]["role"] == role:
                merged[-1]["content"] = merged[-1]["content"] + "\n\n" + content
            else:
                merged.append({"role": role, "content": content})
        # Розмова мусить починатися з користувача.
        if merged and merged[0]["role"] == "assistant":
            merged.insert(0, {"role": "user", "content": "Почнемо."})
        return merged

    @staticmethod
    def _one_question(text: str) -> str:
        """Витягує одну репліку: моделі схильні додавати преамбули й варіанти."""
        clean = (text or "").strip()
        # Прибираємо обрамлення, яке модель іноді додає сама.
        clean = re.sub(r"^```[a-z]*\s*|\s*```$", "", clean).strip()
        clean = clean.strip('"“”«»').strip()
        # Беремо перший рядок, у якому є питання; інакше — перший непорожній.
        lines = [line.strip(" -–—*").strip() for line in clean.splitlines() if line.strip()]
        for line in lines:
            if "?" in line:
                return line
        return lines[0] if lines else ""

    # ── контракт провайдера ──────────────────────────────────────────────

    def respond_text(self, system: str, messages: List[Dict[str, Any]]) -> str:
        conversation = self._alternate(
            [{"role": "user", "content": system}] + list(messages)
        )
        prompt = self._tokenizer.apply_chat_template(conversation, add_generation_prompt=True)
        try:
            with self._lock:
                output = self._generate(
                    self._model, self._tokenizer, prompt=prompt,
                    max_tokens=self.max_tokens, verbose=False,
                )
        except Exception as exc:
            raise ProviderError("Локальна модель не відповіла: %s" % exc)
        question = self._one_question(output)
        if not question:
            raise ProviderError("Локальна модель повернула порожню репліку")
        return question

    def respond_json(self, system, messages, schema, max_tokens=2000):
        # type: (str, List[Dict[str, Any]], Dict[str, Any], int) -> Dict[str, Any]
        raise ProviderError(
            "Локальна модель не дає структурованого виводу — ядро мусить "
            "викликати respond_text (див. supports_structured)."
        )
