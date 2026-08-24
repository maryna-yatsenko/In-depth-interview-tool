"""Живе зарахування: галочка стає тоді, коли людина це проговорила.

Не після надсилання. Це вимога Марини від 23.08.2026: «щоб автоматично, коли
людина проговорює те, що ми хочемо почути, і тільки тоді ставилась галочка», а
далі — «щойно скаже все, стає активною кнопка надіслати».

Головне, що тут перевіряється: чернетка **не рухає рушій**. Людина може сказати
заново, і зароблені галочки мусять зникнути разом із текстом — інакше рушій
вважав би пункт закритим, а в транскрипті не було б нічого.
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


def drain(session, text, limit=12):
    """Жива перевірка до кінця: сервер віддає по одному пункту за виклик.

    Саме так робить клієнт (`runCheck` → `more` → наступний запит), і саме це
    дає першу галочку через ~1,3 с замість ~4 с.
    """
    result = session.evaluate_draft(text)
    for _ in range(limit):
        if not result.get("more"):
            break
        result = session.evaluate_draft(text)
    return result


class Judge(LLMProvider):
    """Двійник оцінювача: закриває пункт лише за словом із самої відповіді.

    Навмисно не за назвою пункта: назва є в КОЖНОМУ запиті («Чи є у цій
    розповіді ось це: «хто ініціював»?»), тому двійник, який дивиться лише на
    неї, закриває пункт ще до того, як людина щось сказала. На цьому й
    спіймався перший підхід до цих тестів.
    """

    name = "judge"
    supports_structured = False

    def __init__(self, rules=None):
        # {назва пункта: слово, яке мусить прозвучати у відповіді}
        self.rules = dict(rules or {})
        self.asked = []

    def respond_text(self, system, messages):
        content = messages[-1]["content"] if messages else ""
        if "Відповідай ОДНИМ словом" in content or "одним словом" in content.lower():
            self.asked.append(content)
            for item, trigger in self.rules.items():
                if item in content and trigger in content:
                    return "так"
            return "ні"
        return "А що саме там сталося?"


def free_mode(guide):
    """Гайд без питань по темах — вільний режим, де питання формулює модель.

    Судження про прогалини живе тільки тут: у сценарному режимі порядок задає
    дослідник, а темп — людина, і модель не вирішує нічого.
    """
    for topic in guide.topics:
        topic.ask_if_missed = ""
        topic.ask_for_detail = ""
    return guide


class TestDraftMarksItems(unittest.TestCase):
    def setUp(self):
        self.space, self.guide = load_space_dir(TRAVEL)
        free_mode(self.guide)

    def _to_topics(self, llm):
        """Доводить сесію до фази уточнень.

        Циклом, а не трьома відповідями: розігрів тепер доперепитує те, чого
        не почув, і кількість ходів залежить від оцінювача.
        """
        session = Session(self.space, self.guide, llm)
        session.start()
        for _ in range(12):
            if session.phase_state.phase == phases.TOPICS:
                break
            session.answer("Та все, більше нічого.")
        return session

    def test_draft_marks_item_before_sending(self):
        topic = self.guide.topics[0]
        llm = Judge({topic.must_learn[0]: "Оля"})
        session = self._to_topics(llm)

        turns_before = len(session.turns)
        result = session.evaluate_draft("Оля запропонувала цю поїздку в грудні.")

        self.assertTrue(result["checklist"][0]["done"])
        # Транскрипт не зачеплений: це чернетка, а не відповідь.
        self.assertEqual(len(session.turns), turns_before)
        # Стан рушія теж: пункт закриє лише надсилання.
        self.assertNotIn(0, session.phase_state.topic_items_done.get(topic.id, []))

    def test_reset_draft_clears_marks(self):
        topic = self.guide.topics[0]
        session = self._to_topics(Judge({topic.must_learn[0]: "Оля"}))
        session.evaluate_draft("Оля запропонувала цю поїздку.")
        self.assertTrue(session.checklist()[0]["done"])

        session.reset_draft()
        self.assertFalse(session.checklist()[0]["done"])

    def test_shrinking_text_drops_marks(self):
        """Людина стерла те, що сказала — галочка не має лишатись."""
        topic = self.guide.topics[0]
        session = self._to_topics(Judge({topic.must_learn[0]: "Оля"}))
        session.evaluate_draft("Оля запропонувала цю поїздку ще в грудні, задовго до.")
        self.assertTrue(session.checklist()[0]["done"])

        session.evaluate_draft("Ну")
        self.assertFalse(session.checklist()[0]["done"])

    def test_editing_the_wording_keeps_the_marks(self):
        """Правка формулювання — не нова відповідь.

        Скарга Марини: «не відмічає те, що вже було сказано». Одна з причин —
        скидання позначок за перевіркою на префікс: людина виправляла початок
        фрази, і все зароблене зникало.
        """
        topic = self.guide.topics[0]
        session = self._to_topics(Judge({topic.must_learn[0]: "Оля"}))
        session.evaluate_draft("Оля запропонувала цю поїздку ще в грудні.")
        self.assertTrue(session.checklist()[0]["done"])

        # Те саме, але з іншим початком — і без нових викликів моделі.
        session.llm.asked = []
        session.evaluate_draft("Взагалі Оля запропонувала цю поїздку ще в грудні.")
        self.assertTrue(session.checklist()[0]["done"],
                        "правка початку зняла зароблену позначку")

    def test_same_answer_recognises_addition_and_replacement(self):
        keep = Session._same_answer
        base = "Їздили в Карпати, у Ворохту, з друзями з університету"
        self.assertTrue(keep(base, base + ", нас було шість"))
        self.assertTrue(keep(base, "Ми " + base.lower()))
        self.assertFalse(keep(base, "Ні, зовсім інша поїздка була в Одесу"))
        self.assertTrue(keep("", "перша фраза"))

    def test_sending_answer_clears_draft_and_engine_takes_over(self):
        topic = self.guide.topics[0]
        session = self._to_topics(Judge({topic.must_learn[0]: "Оля"}))
        session.evaluate_draft("Оля запропонувала цю поїздку.")
        session.answer("Оля запропонувала цю поїздку.")

        self.assertEqual(session.draft_done, [])
        # Тепер це знання рушія, а не чернетки.
        self.assertIn(0, session.phase_state.topic_items_done.get(topic.id, []))

    def test_added_text_closes_item_that_was_missing_before(self):
        """Дописане мусить закривати пункт, якого спершу не почули.

        Спіймано в браузері: перша версія кешувала «цього не почули» й більше
        пункт не перевіряла — тож людина доповнювала відповідь, а галочка не
        зʼявлялась ніколи.
        """
        topic = self.guide.topics[0]
        session = self._to_topics(Judge({topic.must_learn[0]: "Оля"}))

        drain(session, "Поїхали в Карпати на чотири дні, було гарно.")
        self.assertFalse(session.checklist()[0]["done"])

        drain(session, "Поїхали в Карпати на чотири дні, було гарно. "
                       "Запропонувала це Оля ще в грудні.")
        self.assertTrue(session.checklist()[0]["done"])

    def test_draft_is_judged_on_current_words_only(self):
        """Галочка мусить бути наслідком того, що людина каже ЗАРАЗ.

        Спіймано Мариною: людина говорить про інше, а галочка стає. Причина
        була в тому, що жива перевірка судила весь текст інтервʼю разом із
        чернеткою — і зараховувала пункт за старою відповіддю.
        """
        topic = self.guide.topics[0]
        llm = Judge({topic.must_learn[0]: "Оля"})
        session = Session(self.space, self.guide, llm)
        session.start()
        # «Оля» звучить у РОЗІГРІВІ, тобто в попередньому ході.
        session.answer("Поїхали в Карпати, це Оля все організувала.")
        session.answer("Та все.")
        session.answer("Та все, більше нічого.")

        # Пункт може бути вже закритий рушієм — і це правильно, «Оля» справді
        # звучала. Перевіряємо саме ЧЕРНЕТКУ: слова про погоду не мають
        # зараховувати нічого, і в промпт не має потрапляти старий текст.
        llm.asked = []
        session.evaluate_draft("Погода була жахлива, весь час дощ і туман.")

        self.assertEqual(session.draft_done, [],
                         "чернетка зарахувала пункт словами, яких у ній немає")
        self.assertTrue(llm.asked, "оцінювача взагалі не питали")
        for prompt in llm.asked:
            self.assertIn("Погода була жахлива", prompt)
            self.assertNotIn("Поїхали в Карпати", prompt,
                             "у промпт потрапила попередня відповідь")

    def test_one_call_checks_at_most_the_cap(self):
        """Межа на прогін є: кожен пункт — окремий виклик моделі."""
        session = Session(self.space, self.guide, Judge())
        session.start()
        # У розігріві три очікування, межа — три перевірки за прогін.
        session.evaluate_draft("Ми кудись їздили і це було цікаво, ось так.")
        self.assertLessEqual(len(session.llm.asked),
                             Session.MAX_DRAFT_CHECKS_PER_CALL)

    def test_rotation_reaches_every_item_over_several_pauses(self):
        """Довгий список перевіряється по колу, а не завжди перші три."""
        session = Session(self.space, self.guide, Judge())
        session.start()
        seen = set()
        for i in range(4):
            session.llm.asked = []
            session.evaluate_draft("Розповідь номер %d, слова слова слова слова." % i)
            for prompt in session.llm.asked:
                for item in self.guide.opening_expects:
                    if item in prompt:
                        seen.add(item)
        self.assertEqual(seen, set(self.guide.opening_expects))


class TestWarmupAndClosingHaveMarks(unittest.TestCase):
    """Раніше галочки жили лише в темах — у розігріві чекліст стояв порожній."""

    def setUp(self):
        self.space, self.guide = load_space_dir(TRAVEL)
        free_mode(self.guide)

    def test_warmup_item_marked_live(self):
        expects = self.guide.opening_expects
        self.assertTrue(expects, "гайд подорожей має очікування на розігрів")
        session = Session(self.space, self.guide, Judge({expects[0]: "Карпати"}))
        session.start()

        result = session.evaluate_draft("Їздили в Карпати компанією з шести людей.")
        self.assertEqual(session.phase_state.phase, phases.WARMUP)
        self.assertTrue(result["checklist"][0]["done"])

    def test_all_covered_only_when_everything_marked(self):
        expects = self.guide.opening_expects
        session = Session(self.space, self.guide,
                          Judge(dict((e, "Карпати") for e in expects)))
        session.start()
        drain(session, "Їздили в Карпати, шість людей, з друзями.")
        self.assertTrue(session.all_expected_covered())

        session.reset_draft()
        self.assertFalse(session.all_expected_covered())

    def test_no_expectations_is_not_all_covered(self):
        """Порожній чекліст — це «нема чого гейтити», а не «все зараховано»."""
        space, g = load_space_dir(TRAVEL)
        bare = g.__class__(**dict(
            {k: getattr(g, k) for k in g.__dataclass_fields__},
            opening_expects=[]))
        session = Session(space, bare, Judge())
        session.start()
        self.assertFalse(session.all_expected_covered())


class TestNarrativeEndsWhenEverythingHeard(unittest.TestCase):
    """Замість кнопки «Я все розповіла» — повний чекліст тем."""

    def setUp(self):
        self.space, self.guide = load_space_dir(TRAVEL)
        free_mode(self.guide)

    def test_full_coverage_moves_to_topics(self):
        state = phases.PhaseState(phase=phases.NARRATIVE, narrative_count=5)
        plan = phases.Plan(self.guide, lambda text, topics: [])
        state.covered_in_narrative = [t.id for t in self.guide.topics]
        state.narrative_checked = [t.id for t in self.guide.topics]

        action = plan.next_action(state, "довга розповідь про всю поїздку", "текст")
        self.assertEqual(state.phase, phases.TOPICS)
        self.assertIsNotNone(action)

    def test_full_coverage_too_early_does_not_cut_the_story(self):
        """Модель щедра на зарахування — розповідь не має обриватись на початку.

        Гайд дає вільній розповіді 20-25 хвилин і вважає її найціннішою
        частиною. Пара поспішних зарахувань не мусить її закрити.
        """
        state = phases.PhaseState(phase=phases.NARRATIVE)
        plan = phases.Plan(self.guide, lambda text, topics: [])
        state.covered_in_narrative = [t.id for t in self.guide.topics]
        state.narrative_checked = [t.id for t in self.guide.topics]

        action = plan.next_action(state, "довга розповідь про всю поїздку", "текст")
        self.assertEqual(state.phase, phases.NARRATIVE)
        self.assertEqual(action.kind, phases.HOLD)

    def test_partial_coverage_keeps_holding(self):
        state = phases.PhaseState(phase=phases.NARRATIVE)
        plan = phases.Plan(self.guide, lambda text, topics: [])
        state.covered_in_narrative = [self.guide.topics[0].id]
        state.narrative_checked = [t.id for t in self.guide.topics]

        action = plan.next_action(state, "довга розповідь про всю поїздку", "текст")
        self.assertEqual(state.phase, phases.NARRATIVE)
        self.assertEqual(action.kind, phases.HOLD)


if __name__ == "__main__":
    unittest.main()
