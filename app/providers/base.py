"""Інтерфейси провайдерів.

Єдине місце, де інструмент знає про існування зовнішніх вендорів. Правило з
docs/ai/architecture.md: пряме звернення до вендора поза цим пакетом — дефект.

STT/TTS оголошені зараз, хоча реалізуються на Етапі 2. Це не «на майбутнє»:
наявність інтерфейсу з першого дня не дає голосовій специфіці протекти в ядро.
"""

from typing import Any, Dict, List, Optional


class ProviderError(RuntimeError):
    """Вендор не відповів або відповів помилкою. Ядро вирішує, що робити далі."""


class LLMProvider:
    """Модель, яка веде інтервʼю і аналізує транскрипти."""

    name = "base"

    # Чи вміє провайдер приймати system-повідомлення посеред розмови. Якщо ні —
    # ядро доклеює службовий стан до реплики респондента (див. session._messages).
    supports_system_turns = False
    # Чи вміє провайдер віддавати провалідований JSON за схемою. Слабкі локальні
    # моделі не вміють: просити в 4B-моделі JSON — лотерея. Тоді ядро питає
    # текст питання (`respond_text`), а рішення про переходи ухвалює саме —
    # воно й так форсує ліміти уточнень і покриття тем.
    supports_structured = True

    def respond_text(self, system: str, messages: List[Dict[str, Any]]) -> str:
        """Одна репліка інтервʼюера текстом. Для провайдерів без структури."""
        raise NotImplementedError

    def respond_json(
        self,
        system: str,
        messages: List[Dict[str, Any]],
        schema: Dict[str, Any],
        max_tokens: int = 2000,
    ) -> Dict[str, Any]:
        """Повертає провалідований словник за схемою.

        Чому саме JSON, а не вільний текст: реплика інтервʼюера й службове
        рішення («копати далі» / «наступна тема») — різні речі, і змішувати їх
        в одному потоці тексту означає парсити модель регулярками.
        """
        raise NotImplementedError


class STTProvider:
    """Голос респондента → текст. Етап 2."""

    name = "base"

    def transcribe(
        self,
        audio: bytes,
        languages: List[str],
        vocabulary: Optional[List[str]] = None,
    ) -> str:
        """`vocabulary` — словник домену з конфігу простору.

        Це не опція, а причина, чому інструмент універсальний: без підказки
        провайдер калічить лексику будь-якої вузької теми, не тільки юридичної.
        """
        raise NotImplementedError


class TTSProvider:
    """Текст питання → голос."""

    name = "base"
    # Тип аудіо, який віддає провайдер: клієнт не має його вгадувати.
    media_type = "audio/wav"

    def synthesize(self, text: str, voice: Optional[str] = None) -> bytes:
        raise NotImplementedError

    def voices(self) -> List[Dict[str, Any]]:
        """Реальний перелік голосів провайдера: [{"name", "locale", …}].

        Кожен провайдер віддає свої справжні імена. Імена НЕ переносяться між
        провайдерами: системний `say` знає «Lesya», браузер показує «Леся»,
        Azure має власні позначення. Тому голос налаштовується під провайдера.
        """
        return []
