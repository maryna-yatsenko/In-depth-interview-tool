"""Повернення до раніше поставленого питання.

Людина згадує деталь про перше питання вже посеред пʼятої теми. У модерованому
інтервʼю дослідник просто повернувся б до тієї теми; тут це мусить бути дією,
інакше деталь втрачається назавжди.

Головне правило, яке тут перевіряється: **транскрипт тільки на дописування**.
Попередня репліка не переписується — доповнення стає окремим ходом із позначкою
`added_to`. Для дослідника «згадала пізніше» і «сказала одразу» — це різні дані
про людську память, і склеювати їх в одну репліку означало б втратити факт.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.space import load_space_dir
from app.interview import phases
from app.interview.session import Session
from app.providers.base import LLMProvider

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAVEL = os.path.join(ROOT, "spaces", "travel")


class Quiet(LLMProvider):
    """Нічого не зараховує: перевіряємо саму механіку, не оцінювача."""

    name = "quiet"
    supports_structured = False

    def respond_text(self, system, messages):
        content = messages[-1]["content"] if messages else ""
        if "одним словом" in content.lower():
            return "ні"
        return "А що саме там сталося?"


class Generous(Quiet):
    """Зараховує все — щоб побачити, що доповнення переоцінює тему."""

    def respond_text(self, system, messages):
        content = messages[-1]["content"] if messages else ""
        if "одним словом" in content.lower():
            return "так"
        return "А що саме там сталося?"


class TestHistory(unittest.TestCase):
    def setUp(self):
        self.space, self.guide = load_space_dir(TRAVEL)

    def _started(self, llm=None):
        session = Session(self.space, self.guide, llm or Quiet())
        session.start()
        session.answer("Їздили в Карпати, у Ворохту, з друзями, нас було шість.")
        return session

    def test_history_pairs_questions_with_answers(self):
        session = self._started()
        items = session.history()
        self.assertTrue(items)
        first = items[0]
        self.assertIn("Розкажіть", first["question"])
        self.assertEqual(len(first["answers"]), 1)
        self.assertFalse(first["answers"][0]["added"])

    def test_append_lands_under_the_question_it_belongs_to(self):
        """Доповнення лежить у кінці транскрипту, а показується там, де треба.

        Спіймано наживо: групування послідовне ставило доповнення під
        ПОСЛІДНЄ питання, і людина бачила його не там, куди додавала.
        """
        session = self._started()
        session.go(1)
        session.show_current()
        session.answer("Почалось усе з Олі, вона кинула посилання в чат.")
        session.append_to_answer(0, "А ще це було в лютому, на чотири дні.")

        items = session.history()
        first = items[0]
        self.assertEqual(len(first["answers"]), 2)
        self.assertFalse(first["answers"][0]["added"])
        self.assertTrue(first["answers"][1]["added"])
        # І більше ніде: під іншими питаннями доповнення бути не може.
        for other in items[1:]:
            self.assertFalse(any(a["added"] for a in other["answers"]),
                             "доповнення показалось під чужим питанням")

    def test_transcript_is_append_only(self):
        """Попередня репліка не переписується — це первинні дані."""
        session = self._started()
        original = session.turns[1]["text"]
        session.append_to_answer(0, "Ще одна деталь про ту саму поїздку.")

        self.assertEqual(session.turns[1]["text"], original)
        last = session.turns[-1]
        self.assertEqual(last["role"], "respondent")
        self.assertEqual(last["added_to"], 0)
        self.assertTrue(any(i["kind"] == "answer_extended" for i in session.incidents))

    def test_append_does_not_move_the_script(self):
        """Людина повернулась додати деталь, а не почати тему заново."""
        session = self._started()
        before = (session.phase_state.phase, session.phase_state.topic_index,
                  session.phase_state.narrative_count)
        session.append_to_answer(0, "Дописую щось до першого питання.")
        after = (session.phase_state.phase, session.phase_state.topic_index,
                 session.phase_state.narrative_count)
        self.assertEqual(before, after)

    def test_append_reopens_evaluation_of_that_topic(self):
        """Доповнення могло закрити пункт — тему треба переоцінити."""
        session = Session(self.space, self.guide, Generous())
        session.start()
        # Доходимо до першого питання теми: у сценарному режимі це кроки.
        while not session.current_question().get("topic_id"):
            session.answer("Та все, більше нічого не пригадаю.")
            session.go(1)
            session.show_current()
        topic_id = session.current_question()["topic_id"]
        topic = next(t for t in self.guide.topics if t.id == topic_id)
        question_index = max(i for i, t in enumerate(session.turns)
                             if t["role"] == "interviewer")
        session.phase_state.topic_items_done[topic.id] = []

        session.append_to_answer(
            question_index,
            "Розповім докладно: запропонувала Оля ще в грудні, і за два дні "
            "ми вже скидались на завдаток, тобто вийшло швидко.")
        self.assertTrue(session.phase_state.topic_items_done.get(topic.id),
                        "доповнення не переоцінило тему")

    def test_append_rejects_bad_index_and_empty_text(self):
        session = self._started()
        with self.assertRaises(ValueError):
            session.append_to_answer(999, "текст")
        with self.assertRaises(ValueError):
            session.append_to_answer(1, "текст")     # це відповідь, не питання
        with self.assertRaises(ValueError):
            session.append_to_answer(0, "   ")

    def test_append_masks_personal_data_like_any_answer(self):
        """Деідентифікація на вході стосується й доповнень."""
        session = self._started()
        session.append_to_answer(0, "Пишіть мені на olya@example.com, домовимось.")
        self.assertNotIn("olya@example.com", session.turns[-1]["text"])
        self.assertTrue(session.turns[-1].get("masked"))


if __name__ == "__main__":
    unittest.main()
