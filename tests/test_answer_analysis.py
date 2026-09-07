"""Чи відповідь достатньо розгорнута, щоб зарахувати пункт `must_learn`.

Раніше цей файл тестував ще й вільне уточнення моделі під конкретну
прогалину (`_ask_planned`/PROBE) — того механізму більше немає: питання
завжди дослівне з гайда. `_developed_enough` лишається — її викликає
`_resolve_items_for` (при поверненні до питання, `Session.append_to_answer`)
і жива перевірка чернетки (`/api/draft`), і обидві не залежать від того, як
питання потрапило на екран.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.space import load_space_dir
from app.interview.session import Session
from app.providers.base import LLMProvider

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAVEL = os.path.join(ROOT, "spaces", "travel")


class Judge(LLMProvider):
    """Мінімальна заглушка: `_developed_enough` не звертається до моделі
    взагалі, але конструктор `Session` вимагає провайдера."""

    name = "judge"
    supports_structured = False

    def respond_text(self, system, messages):
        return "ні"


class TestDevelopedEnough(unittest.TestCase):
    def setUp(self):
        self.space, self.guide = load_space_dir(TRAVEL)

    def test_story_item_needs_a_developed_answer(self):
        """Пункт, позначений у гайді як розповідь, словом не закривається."""
        topic = next(t for t in self.guide.topics if t.needs_words)
        item = list(topic.needs_words)[0]
        needed = topic.needs_words[item]
        session = Session(self.space, self.guide, Judge())

        short = " ".join(["слово"] * (needed - 1))
        long = " ".join(["слово"] * (needed + 2))
        self.assertFalse(session._developed_enough(short, item, topic))
        self.assertTrue(session._developed_enough(long, item, topic))

    def test_fact_item_has_no_extra_requirement(self):
        """Факту зайва межа лише плодила б непотрібні уточнення."""
        topic = self.guide.topics[1]           # «Де лежали квитки й домовленості»
        fact = topic.must_learn[0]
        self.assertNotIn(fact, topic.needs_words)
        session = Session(self.space, self.guide, Judge())
        self.assertTrue(session._developed_enough("все було в пошті", fact, topic))


if __name__ == "__main__":
    unittest.main()
