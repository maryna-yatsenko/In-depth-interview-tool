"""LLM-провайдер-заглушка: проганяє потік інтервʼю без ключа і без витрат.

Навіщо це в проєкті, а не в тестах: банк реплік і ліміти покриття тем треба
ганяти сотні разів, і платити за це токенами немає сенсу.
"""

import re
from typing import Any, Dict, List

from .base import LLMProvider


class MockLLM(LLMProvider):
    name = "mock"
    supports_system_turns = True

    def __init__(self):
        self._calls = 0

    def respond_json(self, system, messages, schema, max_tokens=2000):
        # type: (str, List[Dict[str, Any]], Dict[str, Any], int) -> Dict[str, Any]
        self._calls += 1

        # Режим банку: схема просить id репліки, а не текст. Список доступних
        # id заглушка бере з самого системного промпту — так само, як його
        # бачить справжня модель.
        ids = re.findall(r"^- `([a-z0-9][a-z0-9_-]*)`", system, re.MULTILINE)
        usable = [i for i in ids if i not in ("opening", "closing")]
        if not usable:
            return {"phrase_id": "", "topic_id": "", "action": "probe", "coverage_note": ""}
        chosen = usable[self._calls % len(usable)]
        return {
            "phrase_id": chosen,
            "topic_id": "",
            "action": "probe" if self._calls % 3 else "next_topic",
            "coverage_note": "mock",
        }
