"""LLM-провайдер-заглушка: проганяє потік інтервʼю без ключа і без витрат.

Навіщо це в проєкті, а не в тестах: машину станів, ліміти покриття тем і
guard-перевірки треба ганяти сотні разів, і платити за це токенами немає сенсу.
Реплики свідомо тупі — це не імітація якості інтервʼю, а перевірка механіки.
"""

import re
from typing import Any, Dict, List

from .base import LLMProvider

_PROBES = [
    "Розкажіть про останній конкретний випадок, коли це сталося.",
    "Що ви зробили далі?",
    "Що сталося потім?",
    "Наведіть приклад.",
]


class MockLLM(LLMProvider):
    name = "mock"
    supports_system_turns = True

    def __init__(self, misbehave: bool = False):
        # misbehave=True змушує заглушку порушувати правила — так тестуємо guard.
        self.misbehave = misbehave
        self._calls = 0

    def respond_json(self, system, messages, schema, max_tokens=2000):
        # type: (str, List[Dict[str, Any]], Dict[str, Any], int) -> Dict[str, Any]
        self._calls += 1

        # Режим банку: схема просить id репліки, а не текст. Список доступних
        # id заглушка бере з самого системного промпту — так само, як його
        # бачить справжня модель.
        if "phrase_id" in (schema.get("properties") or {}):
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
        if self.misbehave:
            return {
                "utterance": "Ви абсолютно праві, це справді незручно. Вам не вистачає фільтра?",
                "topic_id": "",
                "action": "probe",
                "coverage_note": "",
            }
        return {
            "utterance": _PROBES[self._calls % len(_PROBES)],
            "topic_id": "",
            "action": "probe" if self._calls % 3 else "next_topic",
            "coverage_note": "mock",
        }
