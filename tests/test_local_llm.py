"""Шлях для моделей без структурованого виводу.

Просити JSON у 4B-моделі — лотерея: у перевірці вона інструкцію просто
проігнорувала. Тому ядро питає текст, а рішення про переходи ухвалює саме.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.space import load_space_dir
from app.interview.prompt_builder import COMPACT_PROMPT_VERSION, build_system_compact
from app.interview.session import Session
from app.providers.base import LLMProvider, ProviderError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "spaces", "example")


class TextOnly(LLMProvider):
    """Провайдер без структурованого виводу — як локальна модель."""

    name = "text-only"
    supports_structured = False

    def __init__(self, replies):
        self.replies = list(replies)
        self.systems = []
        self.conversations = []

    def respond_text(self, system, messages):
        self.systems.append(system)
        self.conversations.append(messages)
        return self.replies.pop(0) if self.replies else "Що сталося потім?"

    def respond_json(self, system, messages, schema, max_tokens=2000):
        raise ProviderError("не мусить викликатись")


class TestNonStructuredPath(unittest.TestCase):
    def setUp(self):
        self.space, self.guide = load_space_dir(EXAMPLE)
        self.space.repertoire = "free"

    def _session(self, replies):
        return Session(self.space, self.guide, TextOnly(replies))

    def test_compact_prompt_chosen_automatically(self):
        """Повний промпт коштує локальній моделі вп'ятеро більше часу."""
        session = self._session(["Що ви зробили далі?"])
        self.assertEqual(session.prompt_version, COMPACT_PROMPT_VERSION)
        self.assertIsNone(session.system)

    def test_json_never_requested(self):
        session = self._session(["Що ви зробили далі?"])
        session.start()
        session.answer("щось")   # respond_json кинув би ProviderError

    def test_transcript_records_compact_version(self):
        session = self._session(["Що ви зробили далі?"])
        session.start()
        session.answer("щось")
        self.assertEqual(session.to_dict()["prompt_version"], COMPACT_PROMPT_VERSION)

    def test_core_still_forces_topic_change(self):
        """Модель не вирішує переходів — їх форсують ліміти."""
        first = self.guide.topics[0]
        replies = ["Питання номер %d про досвід?" % i for i in range(first.max_probes + 3)]
        session = self._session(replies)
        session.start()
        overrides = []
        for _ in range(first.max_probes + 1):
            turn = session.answer("щось нове")
            if turn.override:
                overrides.append(turn.override)
        self.assertTrue(any("ліміт уточнень" in o for o in overrides))

    def test_guard_still_rejects_leading_question(self):
        session = self._session(["Вам не вистачає фільтра?", "Що ви зробили далі?"])
        session.start()
        turn = session.answer("відповідь")
        self.assertTrue(turn.guard_rejections)
        self.assertEqual(turn.utterance, "Що ви зробили далі?")

    def test_fallback_after_three_bad_replies(self):
        session = self._session(["Чудово! Вам не вистачає X?"] * 3)
        session.start()
        turn = session.answer("відповідь")
        self.assertTrue(turn.fallback_used)

    def test_conversation_passed_without_state_block(self):
        """Службовий стан потрібен для рішень моделі, а їх тут ухвалює ядро."""
        session = self._session(["Що ви зробили далі?"])
        session.start()
        session.answer("моя відповідь")
        conversation = session.llm.conversations[-1]
        self.assertTrue(all("СЛУЖБОВИЙ СТАН" not in m["content"] for m in conversation))
        self.assertEqual(conversation[-1]["content"], "моя відповідь")

    def test_compact_system_mentions_topic_as_direction(self):
        topic = self.guide.topics[0]
        system = build_system_compact(self.space, self.guide, topic)
        self.assertIn("НАПРЯМОК РОЗМОВИ", system)
        self.assertIn(topic.title, system)
        # Опис must_learn навмисно НЕ вкладається: модель починала питати його
        # буквально й перестала слухати розмову.
        for item in topic.must_learn:
            self.assertNotIn(item, system)

    def test_compact_system_is_much_shorter(self):
        from app.interview.prompt_builder import build_system
        full = build_system(self.space, self.guide)
        compact = build_system_compact(self.space, self.guide, self.guide.topics[0])
        self.assertLess(len(compact), len(full) / 2)


if __name__ == "__main__":
    unittest.main()
