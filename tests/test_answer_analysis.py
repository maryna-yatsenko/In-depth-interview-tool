"""Аналіз відповіді одразу: чи закрила вона прогалину, яку ми закриваємо.

Це відповідь на вимогу «якщо респондент не до кінця розкрив тему — задати
додаткове питання, щоб дізнатися все, що потрібно». Прогалини — це `must_learn`
дослідника, а не догадки моделі.
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


class Judge(LLMProvider):
    """Модель, яка каже «так» на задані відповіді й формулює уточнення."""

    name = "judge"
    supports_structured = False

    def __init__(self, closes=()):
        self.closes = set(closes)
        self.asked_about = []
        self.judgements = []

    def respond_text(self, system, messages):
        content = messages[-1]["content"] if messages else ""
        if "Відповідай ОДНИМ словом" in content:
            self.judgements.append(content)
            return "так" if any(c in content for c in self.closes) else "ні"
        # Уточнення: запамʼятовуємо, чи прийшов фокус у промпт.
        self.asked_about.append(system)
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


class TestAnswerAnalysis(unittest.TestCase):
    def setUp(self):
        self.space, self.guide = load_space_dir(TRAVEL)
        free_mode(self.guide)

    def _run_to_topics(self, llm):
        """Доводить сесію до фази уточнень.

        Не фіксованою кількістю відповідей: розігрів тепер може доперепитати
        прогалину, і кількість ходів залежить від того, що зарахував оцінювач.
        """
        session = Session(self.space, self.guide, llm)
        session.start()
        for _ in range(12):
            if session.phase_state.phase == phases.TOPICS:
                break
            session.answer("Та все, більше нічого.")
        return session

    def test_one_word_credits_nothing(self):
        """«Оля.» — це не відповідь на «хто запропонував поїхати».

        Вимога Марини: одного слова недостатньо, людина мусить відповісти
        розгорнуто. Перевірка стоїть ДО моделі: навіть якщо оцінювач скаже
        «так», пункт лишається відкритим.
        """
        expects = self.guide.opening_expects
        # Оцінювач тут згоден зарахувати все — межу тримає рушій, не він.
        llm = Judge(closes=list(expects))
        session = Session(self.space, self.guide, llm)
        session.start()

        # Сервер оцінює по одному пункту за виклик — добираємо, як клієнт.
        for _ in range(4):
            session.evaluate_draft("Карпати")
        self.assertEqual(session.draft_done, [],
                         "одне слово зарахувало пункт")

        for _ in range(4):
            session.evaluate_draft("Їздили в Карпати")
        self.assertTrue(session.checklist()[0]["done"],
                        "коротка, але повна відповідь на факт мусить зараховуватись")

    def test_story_item_needs_a_developed_answer(self):
        """Пункт, позначений у гайді як розповідь, словом не закривається."""
        topic = next(t for t in self.guide.topics if t.needs_words)
        item = list(topic.needs_words)[0]
        needed = topic.needs_words[item]
        session = Session(self.space, self.guide, Judge(closes=[item]))

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

    def test_warmup_asks_again_when_facts_are_missing(self):
        """Людина не сказала фактів — інтервʼюер мусить доперепитати.

        Скарга Марини: «В Карпати їздили» закриває один пункт із трьох, а
        інтервʼюер ішов далі до вільної розповіді. Чекліст обіцяв «хочемо
        почути» і обіцянки не виконував.
        """
        expects = self.guide.opening_expects
        # Оцінювач зараховує лише «куди їздили» — решта лишається відкритою.
        llm = Judge(closes=[expects[0]])
        session = Session(self.space, self.guide, llm)
        session.start()

        turn = session.answer("В Карпати їздили.")
        self.assertEqual(session.phase_state.phase, phases.WARMUP,
                         "рушій пішов далі, не спитавши про прогалину")
        self.assertEqual(turn.source, "opening-gap")
        self.assertTrue(turn.utterance, "доуточнення без тексту")

    def test_warmup_moves_on_when_everything_was_said(self):
        """А якщо все сказано — жодного зайвого питання."""
        llm = Judge(closes=list(self.guide.opening_expects))
        session = Session(self.space, self.guide, llm)
        session.start()

        session.answer("Їздили в Карпати з друзями, нас було шість.")
        self.assertEqual(session.phase_state.phase, phases.NARRATIVE,
                         "усе почули, а рушій усе одно доперепитує")

    def test_warmup_probes_are_bounded(self):
        """Пункт, якого людина не знає, не має тримати її назавжди."""
        session = Session(self.space, self.guide, Judge(closes=[]))
        session.start()
        for _ in range(phases.MAX_OPENING_PROBES + 2):
            if session.phase_state.phase != phases.WARMUP:
                break
            session.answer("Не пам'ятаю.")
        self.assertEqual(session.phase_state.phase, phases.NARRATIVE)
        self.assertLessEqual(session.phase_state.opening_probes,
                             phases.MAX_OPENING_PROBES)

    def test_closing_asks_again_when_expectation_unmet(self):
        """Те саме в підсумку: там теж стояв чекліст, який ні на що не впливав."""
        session = Session(self.space, self.guide, Judge(closes=[]))
        session.phase_state.phase = phases.CLOSING
        session.phase_state.closing_index = 1
        turn = session.answer("Та нічого особливого.")
        self.assertEqual(turn.source, "closing-gap")
        self.assertEqual(session.phase_state.closing_probes.get(0), 1)

    def test_answer_is_labelled_with_the_topic_it_belongs_to(self):
        """Відповідь підписується поточною темою, а не першою.

        `topic_index` у режимі сценарію не рухається — той самий корінь, що й у
        бага з прогресом. Через нього кожна відповідь підписувалась темою 1, і
        оцінка, звужена до «цієї ж теми», не знаходила нічого.
        """
        session = self._run_to_topics(Judge())
        session.phase_state.topic_index = 2
        session.answer("Відповідь у третій темі.")
        spoken = [t for t in session.turns if t["role"] == "respondent"]
        self.assertEqual(spoken[-1]["topic_id"], self.guide.topics[2].id)
        self.assertEqual(spoken[-1]["phase"], "topics")

    def test_other_topics_answers_do_not_close_this_topic(self):
        """Відповідь на іншу тему не має закривати пункти цієї.

        Спостережено на повному прогоні: відповіді про розподіл внеску й гроші
        закрили пункти тем «Розбіжна інформація», «Розбіжність поглядів» і
        «Поведінка на місці» — рушій не спитав про них узагалі, і три теми
        дослідження зникли молча.
        """
        first, second = self.guide.topics[0], self.guide.topics[1]
        # Оцінювач тут щедрий свідомо: каже «так» на будь-який пункт, якщо в
        # тексті є слово-тригер. Саме така щедрість і робила пропуски.
        llm = Judge(closes=[second.must_learn[0]])
        session = self._run_to_topics(llm)

        # Відповідь у ПЕРШІЙ темі. Пункт другої теми закритись не має.
        session.answer("Оля запропонувала цю поїздку, тригер тут є.")
        self.assertNotIn(0, session.phase_state.topic_items_done.get(second.id, []),
                         "пункт другої теми закрила відповідь на першу")

    def test_narrative_still_closes_items_of_any_topic(self):
        """А розповідь — має: там людина говорить про все підряд."""
        topic = self.guide.topics[1]
        llm = Judge(closes=[topic.must_learn[0]])
        session = Session(self.space, self.guide, llm)
        session.start()
        session.answer("Їздили в Карпати, шість людей.")
        # Це вільна розповідь: тут пункт будь-якої теми може прозвучати.
        session.answer("Довга розповідь, у якій прозвучало все потрібне.")
        session.answer("Та все, більше нічого.")
        session.answer("Та все.")

        said = session._said_for_topic(topic)
        self.assertIn("Довга розповідь", said,
                      "розповідь мусить лишатись у полі зору оцінювача")

    def test_answer_closing_item_marks_it_done(self):
        topic = self.guide.topics[0]
        llm = Judge(closes=[topic.must_learn[0]])
        session = self._run_to_topics(llm)
        session.answer("Оля запропонувала цю поїздку.")
        self.assertIn(0, session.phase_state.topic_items_done.get(topic.id, []))

    def test_answer_not_closing_item_leaves_it_open(self):
        llm = Judge(closes=[])
        session = self._run_to_topics(llm)
        session.answer("Та якось саме вийшло.")
        topic = self.guide.topics[0]
        self.assertEqual(session.phase_state.topic_items_done.get(topic.id, []), [])

    def test_all_open_items_judged_but_bounded(self):
        """Одна відповідь часто закриває кілька пунктів («Оля запропонувала за
        місяць до поїздки»), тому оцінюються всі відкриті — але не більше межі,
        бо кожен пункт це окремий виклик моделі."""
        from app.interview.session import Session as S
        topic = self.guide.topics[0]
        llm = Judge(closes=[])
        session = self._run_to_topics(llm)
        before = len(llm.judgements)
        session.answer("Щось відповів.")
        checked = len(llm.judgements) - before
        self.assertGreaterEqual(checked, 1)
        self.assertLessEqual(checked, S.MAX_ITEM_CHECKS_PER_TURN)
        self.assertIn(topic.must_learn[0], " ".join(llm.judgements[before:]))

    def test_judgement_sees_everything_said_not_just_last_answer(self):
        """Пункт, що прозвучав у вільній розповіді, мусить закриватись.

        Раніше оцінка бачила лише останню відповідь — і репліка про час
        зараховувала пункт «хто ініціював», бо про «хто» йшлося раніше.
        """
        llm = Judge(closes=[])
        session = self._run_to_topics(llm)
        session.answer("Оля запропонувала цю поїздку.")
        session.answer("А ще ми довго не могли обрати дати.")
        self.assertTrue(any("Оля запропонувала" in j for j in llm.judgements),
                        "оцінка не побачила попередніх реплік")

    # ПРИБРАНО: test_redundant_question_skipped_when_topic_closes.
    #
    # Перевіряв перевибір ходу, коли оцінка закрила тему до того, як звучало
    # вже вибране питання рівня 1/2. Такої ситуації більше немає ні в одному
    # режимі: у сценарному питання по темах веде людина (і сама пропускає
    # зайве кнопкою «наступне»), а у вільному режимі фіксованих питань по темах
    # узагалі немає — їх формулює модель. Разом із тестом прибрано й мертвий
    # код перевибору в `_ask_planned`.

    def test_open_items_reported_in_transcript(self):
        """Перелік незакритого — прямий матеріал для «Нотаток для себе» гайда."""
        llm = Judge(closes=[])
        session = self._run_to_topics(llm)
        session.answer("Щось відповів.")
        report = session.to_dict()["open_items"]
        self.assertIn(self.guide.topics[0].id, report)
        self.assertIn(self.guide.topics[0].must_learn[0], report[self.guide.topics[0].id])

    def test_closed_items_recorded_as_incidents(self):
        topic = self.guide.topics[0]
        llm = Judge(closes=[topic.must_learn[0]])
        session = self._run_to_topics(llm)
        session.answer("Оля запропонувала.")
        kinds = [i["kind"] for i in session.incidents]
        self.assertIn("item_closed", kinds)

    def test_probe_prompt_carries_the_gap(self):
        """Уточнення мусить питати саме про незакритий пункт, а не «щось по темі»."""
        topic = self.guide.topics[0]
        topic.max_probes = 5
        llm = Judge(closes=[])
        session = self._run_to_topics(llm)
        session.answer("Перша відповідь.")     # рівень 2
        session.answer("Друга відповідь.")     # уточнення з фокусом
        self.assertTrue(llm.asked_about, "модель не отримала промпту уточнення")
        self.assertTrue(any("СПИТАЙ САМЕ ПРО ЦЕ" in s for s in llm.asked_about))
        self.assertTrue(any(topic.must_learn[0] in s for s in llm.asked_about))

    def test_broken_judge_leaves_item_open(self):
        """Не змогли оцінити — вважаємо незакритим: зайве уточнення дешевше
        за прогалину в даних."""
        class Broken(Judge):
            def respond_text(self, system, messages):
                content = messages[-1]["content"] if messages else ""
                if "Відповідай ОДНИМ словом" in content:
                    raise RuntimeError("модель впала")
                return "А що саме там сталося?"

        session = self._run_to_topics(Broken())
        session.answer("Оля запропонувала.")
        self.assertEqual(session.phase_state.topic_items_done.get(self.guide.topics[0].id, []), [])


if __name__ == "__main__":
    unittest.main()
