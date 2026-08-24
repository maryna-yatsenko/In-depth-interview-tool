"""Сценарний режим: порядок задає гайд, темп — людина.

Це рішення 23.08.2026. Раніше перехід між питаннями залежав від того, чи
«зарахувала» модель сказане. Мірка показала, чого це варте: 64-71 % на
контрольному наборі й одна з трьох помилок сорту «відповідь поруч, але не та»
(`app/interview/judge.py`). На такому судженні тримати людину на питанні
неправильно.

Тому в сценарному режимі:
— чекліст — **шпаргалка**, без позначок «зараховано»;
— уперед і назад ходить людина кнопками;
— модель не викликається взагалі, поки не попросять озвучити питання.
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
EXAMPLE = os.path.join(ROOT, "spaces", "example")


class Counting(LLMProvider):
    """Рахує звернення до моделі. У сценарному режимі їх мусить не бути."""

    name = "counting"
    supports_structured = False

    def __init__(self):
        self.calls = 0

    def respond_text(self, system, messages):
        self.calls += 1
        return "ні"


class TestScriptedFlow(unittest.TestCase):
    def setUp(self):
        self.space, self.guide = load_space_dir(TRAVEL)
        self.llm = Counting()
        self.session = Session(self.space, self.guide, self.llm)

    def test_script_follows_the_guide(self):
        script = self.session.script
        self.assertTrue(script)
        self.assertEqual(script[0]["id"], "opening")
        self.assertEqual(script[1]["id"], "narrative")
        # Обидва рівні питань теми стоять по порядку: зайве людина пропускає.
        ids = [item["id"] for item in script]
        self.assertIn("idea/1", ids)
        self.assertIn("idea/2", ids)
        self.assertTrue(ids[-1].startswith("closing/"))

    def test_model_is_not_asked_anything(self):
        """Головне: у цьому режимі модель не вирішує нічого."""
        self.session.start()
        self.session.answer("Їздили в Карпати, у Ворохту, з друзями.")
        self.session.go(1)
        self.session.show_current()
        self.session.answer("Почалось усе з Олі.")
        self.assertEqual(self.llm.calls, 0,
                         "модель викликали %d разів" % self.llm.calls)

    def test_checklist_is_a_plan_without_marks(self):
        self.session.start()
        plan = self.session.checklist()
        self.assertEqual([item["text"] for item in plan],
                         list(self.guide.opening_expects))
        self.assertTrue(all(not item["done"] for item in plan))

        # І після відповіді нічого не «зараховується».
        self.session.answer("Їздили в Карпати з друзями, нас було шість людей.")
        self.assertTrue(all(not item["done"] for item in self.session.checklist()))

    def test_forward_needs_an_answer(self):
        """Інакше людина проклацає інтервʼю, і в даних лишиться порожньо."""
        self.session.start()
        self.assertFalse(self.session.answered_current())
        self.session.answer("Їздили в Карпати.")
        self.assertTrue(self.session.answered_current())

    def test_back_and_forth_shows_what_was_said(self):
        """«Попереднє» мусить показувати відповідь, а не порожнє поле."""
        self.session.start()
        self.session.answer("Їздили в Карпати, у Ворохту.")
        self.session.go(1)
        self.session.show_current()
        self.session.answer("Почалось усе з Олі.")

        self.session.go(-1)
        self.assertEqual(self.session.answers_for_current(),
                         ["Їздили в Карпати, у Ворохту."])
        self.session.go(1)
        self.assertEqual(self.session.answers_for_current(), ["Почалось усе з Олі."])

    def test_question_enters_transcript_once(self):
        """Навігація туди-сюди не плодить дублікатів питання."""
        self.session.start()
        self.session.answer("Їздили в Карпати.")
        for _ in range(3):
            self.session.go(1)
            self.session.show_current()
            self.session.go(-1)
            self.session.show_current()
        asked = [t for t in self.session.turns if t["role"] == "interviewer"]
        self.assertEqual(len(asked), 2, "питання потрапило в транскрипт двічі")

    def test_bounds_are_hard(self):
        self.session.start()
        self.session.go(-5)
        self.assertTrue(self.session.at_start())
        self.session.go(len(self.session.script) + 5)
        self.assertTrue(self.session.at_end())

    def test_finish_is_a_separate_action(self):
        """Випадково завершити розмову людина не має."""
        self.session.start()
        self.session.go(len(self.session.script))
        self.assertTrue(self.session.at_end())
        self.assertFalse(self.session.done)
        text = self.session.finish()
        self.assertTrue(self.session.done)
        self.assertEqual(text, self.guide.closing)

    def test_progress_counts_real_questions(self):
        """«Питання 3 з 25» — тепер це правда, а не межа гайда."""
        self.session.start()
        info = self.session.progress_info()
        self.assertIn("питання 1 з %d" % len(self.session.script), info["detail"])
        self.assertEqual([s["title"] for s in info["sections"]],
                         ["Початок", "Розповідь", "Уточнення", "Підсумок"])
        self.assertTrue(info["scripted"])

    def test_sections_carry_question_counts_and_progress(self):
        """Кожен розділ показує, скільки в ньому питань і скільки відповіли.

        Це і є сходинковий прогрес: не позиція курсора (яку легко сплутати з
        «зроблено»), а реальна кількість відповідей у розділі.
        """
        self.session.start()
        opening = next(s for s in self.session.progress_info()["sections"]
                      if s["phase"] == phases.WARMUP)
        self.assertEqual(opening["total"], 1)
        self.assertEqual(opening["answered"], 0)
        self.assertTrue(opening["current"])

        self.session.answer("Їздили в Карпати, у Ворохту, з друзями.")
        opening = next(s for s in self.session.progress_info()["sections"]
                      if s["phase"] == phases.WARMUP)
        self.assertEqual(opening["answered"], 1)

    def test_depth_stats_count_distinct_questions(self):
        """Глибина рахує ПИТАННЯ, а не ходи: дві репліки на одне питання —
        це одна відповідальна одиниця, довша, не дві."""
        self.session.start()
        self.session.answer("Їздили в Карпати.")
        depth = self.session.progress_info()["depth"]
        self.assertEqual(depth["answered"], 1)
        self.assertEqual(depth["total"], len(self.session.script))
        self.assertGreater(depth["avg_words"], 0)


class TestCursorSurvivesRoundtrip(unittest.TestCase):
    """/api/resume «забував», на якому питанні стояла людина — курсор не
    зберігався взагалі. Відновлена сесія починала з питання 0."""

    def setUp(self):
        self.space, self.guide = load_space_dir(TRAVEL)

    def test_cursor_persists_through_to_dict_from_dict(self):
        session = Session(self.space, self.guide, Counting())
        session.start()
        session.answer("Їздили в Карпати.")
        session.go(1)
        session.show_current()
        self.assertEqual(session.cursor, 1)

        restored = Session.from_dict(self.space, self.guide, Counting(),
                                     session.to_dict())
        self.assertEqual(restored.cursor, 1)
        self.assertEqual(restored.current_question()["id"],
                         session.current_question()["id"])

    def test_old_saves_without_cursor_field_fall_back_to_last_question(self):
        """Сесії, збережені до появи цього поля, не мають відкочуватись на 0."""
        session = Session(self.space, self.guide, Counting())
        session.start()
        session.answer("Їздили в Карпати.")
        session.go(1)
        session.show_current()
        data = session.to_dict()
        del data["state"]["cursor"]

        restored = Session.from_dict(self.space, self.guide, Counting(), data)
        self.assertEqual(restored.cursor, 1)


class Structured(Counting):
    """Двійник структурованого провайдера (як Anthropic) — інший `prompt_version`."""
    supports_structured = True


class TestResumeAcrossProviders(unittest.TestCase):
    """Головна знахідка: /api/resume не працював ЖОДНОГО РАЗУ для локальної
    моделі (MLX), бо перевірка звіряла збережену версію промпту з фіксованим
    DEFAULT_PROMPT_VERSION замість тієї, яку дає поточний провайдер. MLX не
    структурований → отримує `interviewer.compact` → ніколи не збігався з
    жорстко зашитим `interviewer.v1` → resume падав з ValueError щоразу, коли
    сесія не лишалась у памʼяті процесу (тобто після кожного перезапуску
    сервера — саме те, заради чого існує TD-5).
    """

    def setUp(self):
        self.space, self.guide = load_space_dir(TRAVEL)

    def test_same_kind_of_provider_resumes_fine(self):
        """Це і є виправлення: той самий тип провайдера — resume проходить."""
        session = Session(self.space, self.guide, Counting())   # non-structured
        session.start()
        session.answer("Їздили в Карпати.")
        restored = Session.from_dict(self.space, self.guide, Counting(),
                                     session.to_dict())
        self.assertEqual(restored.session_id, session.session_id)

    def test_genuinely_different_provider_still_rejected(self):
        """Захист не зник: НАСПРАВДІ інший провайдер (інший формат промпту)
        і далі не дозбирається — це лишається правильною поведінкою."""
        session = Session(self.space, self.guide, Counting())   # compact
        session.start()
        data = session.to_dict()
        with self.assertRaises(ValueError):
            Session.from_dict(self.space, self.guide, Structured(), data)  # v1


class TestAppendCountsAsAnAnswer(unittest.TestCase):
    """Доповнення без question_id не бачили ні answered_current, ні глибина."""

    def setUp(self):
        self.space, self.guide = load_space_dir(TRAVEL)
        self.session = Session(self.space, self.guide, Counting())
        self.session.start()

    def test_append_is_visible_to_answers_for_current(self):
        self.session.append_to_answer(0, "Це доповнення до першого питання.")
        self.assertIn("Це доповнення до першого питання.",
                      self.session.answers_for_current())

    def test_append_counts_in_depth_stats(self):
        self.session.append_to_answer(0, "Слово слово слово слово слово.")
        depth = self.session.progress_info()["depth"]
        self.assertEqual(depth["answered"], 1)

    def test_append_carries_explicit_voice_clips(self):
        """Голос доповнення приходить явно від клієнта, а не з pending_voice:
        інакше запис, що чекає на СВОЄ /api/answer, украли б."""
        self.session.pending_voice.append("сторонній-запис.webm")
        self.session.append_to_answer(0, "Ще дещо про поїздку.",
                                      voice=["append-01.webm"])
        item = next(i for i in self.session.history() if i["index"] == 0)
        self.assertEqual(item["answers"][0]["voice"], ["append-01.webm"])
        # pending_voice лишається недоторканим — воно про інше питання.
        self.assertEqual(self.session.pending_voice, ["сторонній-запис.webm"])

    def test_append_without_voice_carries_none(self):
        self.session.append_to_answer(0, "Без запису.")
        item = next(i for i in self.session.history() if i["index"] == 0)
        self.assertEqual(item["answers"][0]["voice"], [])


class TestHistoryExposesExpectedPoints(unittest.TestCase):
    """Доповнюючи питання, людина мусить бачити, чого від неї чекали —
    не лише текст питання."""

    def setUp(self):
        self.space, self.guide = load_space_dir(TRAVEL)
        self.session = Session(self.space, self.guide, Counting())
        self.session.start()

    def test_history_carries_the_same_expects_as_the_script_item(self):
        item = next(i for i in self.session.history() if i["index"] == 0)
        self.assertEqual(item["expects"], self.session.script[0]["expects"])
        self.assertTrue(item["expects"])


class TestFreeModeStillWorks(unittest.TestCase):
    """Простір без питань по темах веде розмову моделлю — і це інший інструмент."""

    def test_space_without_topic_questions_has_no_script(self):
        space, guide = load_space_dir(EXAMPLE)
        session = Session(space, guide, Counting())
        self.assertEqual(session.script, [],
                         "простір без питань по темах пішов сценарним режимом")

    def test_travel_space_is_scripted(self):
        space, guide = load_space_dir(TRAVEL)
        session = Session(space, guide, Counting())
        self.assertTrue(session.script)


if __name__ == "__main__":
    unittest.main()
