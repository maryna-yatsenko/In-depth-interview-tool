"""Сценарій гайда: розігрів → вільна розповідь → карта тем → підсумок.

Це найважливіший рушій інструменту: він веде інтервʼю дослівними формулюваннями
дослідника, а модель викликає лише там, де потрібне вільне уточнення. Тому
тестується без моделі взагалі.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.space import Guide, Topic, load_space_dir
from app.interview import phases

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAVEL = os.path.join(ROOT, "spaces", "travel")


def free_mode(guide):
    """Гайд без питань по темах — вільний режим, де питання формулює модель."""
    for topic in guide.topics:
        topic.ask_if_missed = ""
        topic.ask_for_detail = ""
    return guide


def guide(**kwargs):
    base = dict(
        key="g", goal="мета",
        topics=[
            Topic(id="t1", title="Перша тема", ask_if_missed="Питання рівня один?",
                  ask_for_detail="Питання рівня два?", max_probes=2,
                  must_learn=["щось перше"]),
            Topic(id="t2", title="Друга тема", ask_if_missed="Друге рівня один?",
                  ask_for_detail="Друге рівня два?", max_probes=2,
                  must_learn=["щось друге"]),
        ],
        opening="Розкажіть коротко.",
        closing="Дякую.",
        narrative_prompt="Розкажіть усю історію.",
        narrative_turns=3,
        narrative_holds=["Ага.", "І що далі?"],
        closing_questions=["Що забрало найбільше часу?", "Що муляло?"],
        deepening=["А конкретно останнього разу?", "І що сталось далі?"],
        generalization_markers=["завжди", "зазвичай"],
    )
    base.update(kwargs)
    return Guide(**base)


class TestFlow(unittest.TestCase):
    def setUp(self):
        self.guide = guide()
        self.plan = phases.Plan(self.guide, coverage_detector=lambda text, topics: [])
        self.state = phases.PhaseState()

    def step(self, answer, narrative=""):
        return self.plan.next_action(self.state, answer, narrative)

    def reach_topics(self):
        """Дійти до карти тем так, як велить гайд.

        Правило гайда: після короткої відповіді ще тримаємо паузу — «найцінніша
        деталь часто звучить саме після паузи». Тому розповідь завершується
        лише на ДРУГІЙ короткій відповіді підряд.
        """
        self.step("коротко")                                   # → narrative
        self.step("Та все.")                                   # пауза, ще тримаємо
        return self.step("Та все, більше нічого.")             # → topics

    def test_warmup_goes_to_narrative_prompt(self):
        action = self.step("Їздили в Карпати.")
        self.assertEqual(action.kind, phases.FIXED)
        self.assertEqual(action.text, "Розкажіть усю історію.")
        self.assertEqual(self.state.phase, phases.NARRATIVE)

    def test_narrative_holds_say_nothing(self):
        """У фазі розповіді інтервʼюер МОВЧИТЬ.

        У гайді тут стоять «ага» й «і що далі», але це репліки живої розмови,
        де вони звучать паралельно з мовленням. У покроковому інтерфейсі вони
        перетворюються на окреме питання «Ага.» — і людина думає, що її про
        щось спитали. Тому тримання не має тексту зовсім.
        """
        self.step("коротко")                      # → narrative
        first = self.step("довга розповідь про поїздку і все що там було")
        second = self.step("ще більше деталей про житло і квитки")
        for action in (first, second):
            self.assertEqual(action.kind, phases.HOLD)
            self.assertEqual(action.text, "")
            self.assertEqual(action.label, "narrative-hold")

    def test_first_short_answer_still_holds(self):
        """Правило гайда: пауза після мовчання — найцінніше звучить після неї."""
        self.step("коротко")
        action = self.step("Та все.")
        self.assertEqual(action.label, "narrative-hold")
        self.assertEqual(self.state.phase, phases.NARRATIVE)

    def test_second_short_answer_ends_narrative(self):
        self.step("коротко")
        self.step("Та все.")
        action = self.step("Та все, більше нічого.")
        self.assertEqual(self.state.phase, phases.TOPICS)
        self.assertIn(action.label, ("topic-level1", "topic-level2"))

    def test_narrative_ends_on_turn_limit(self):
        self.step("коротко")
        for _ in range(self.guide.narrative_turns):
            self.step("довга змістовна відповідь без коротких слів у ній")
        self.assertEqual(self.state.phase, phases.TOPICS)

    def test_level1_when_topic_not_covered(self):
        action = self.reach_topics()
        self.assertEqual(action.label, "topic-level1")
        self.assertEqual(action.text, "Питання рівня один?")

    def test_level2_when_topic_already_covered(self):
        """Правило гайда: не питати вдруге про те, що вже прозвучало."""
        plan = phases.Plan(self.guide, coverage_detector=lambda text, topics: ["t1"])
        state = phases.PhaseState()
        plan.next_action(state, "коротко", "")
        plan.next_action(state, "Та все.", "розповідь")
        action = plan.next_action(state, "Та все, більше нічого.", "розповідь")
        self.assertEqual(action.label, "topic-level2")
        self.assertEqual(action.text, "Питання рівня два?")

    def test_deepening_fires_on_generalization(self):
        self.reach_topics()
        action = self.step("Ми зазвичай усе робимо в чаті.")
        self.assertEqual(action.label, "deepening")
        self.assertEqual(action.text, "А конкретно останнього разу?")

    def test_deepening_walks_the_ladder(self):
        self.reach_topics()
        first = self.step("Ми завжди так робимо.")
        second = self.step("Ну зазвичай хтось один займається.")
        self.assertEqual(first.text, self.guide.deepening[0])
        self.assertEqual(second.text, self.guide.deepening[1])

    def test_deepening_resets_after_concrete_answer(self):
        self.reach_topics()
        self.step("Ми завжди так робимо.")          # драбина: сходинка 1
        self.step("Останнього разу Оля написала в чат у березні.")   # конкретика
        action = self.step("Ми зазвичай усе в чаті.")
        self.assertEqual(action.text, self.guide.deepening[0], "драбина не скинулась")

    def test_level2_follows_level1_as_the_move_to_specifics(self):
        """У гайда рівень 2 і є ходом «до конкретики» — його не мусить
        підміняти вільне уточнення від моделі."""
        self.reach_topics()                                  # рівень 1
        action = self.step("Конкретна відповідь без узагальнень зовсім.")
        self.assertEqual(action.label, "topic-level2")
        self.assertEqual(action.kind, phases.FIXED)

    def test_probe_only_after_both_levels_used(self):
        """Вільне уточнення можливе лише коли обидва рівні вже вжиті І ліміт
        питань у темі це дозволяє. При max_probes=2 обидва рівні його вичерпують,
        і тема закривається без моделі — саме цього гайд і хоче."""
        wide = guide()
        wide.topics[0].max_probes = 3
        plan = phases.Plan(wide, coverage_detector=lambda t, x: [])
        state = phases.PhaseState()
        plan.next_action(state, "коротко", "")
        plan.next_action(state, "Та все.", "")
        plan.next_action(state, "Та все, більше нічого.", "")   # рівень 1
        plan.next_action(state, "Конкретна відповідь.", "")     # рівень 2
        action = plan.next_action(state, "Ще одна конкретна відповідь.", "")
        self.assertEqual(action.kind, phases.PROBE)

    def test_two_levels_close_the_topic_when_limit_is_two(self):
        self.reach_topics()                                     # t1 рівень 1
        self.step("Конкретна відповідь.")                       # t1 рівень 2
        action = self.step("Ще конкретна відповідь.")
        self.assertEqual(action.label, "topic-level1", "не перейшли до наступної теми")
        self.assertEqual(action.text, "Друге рівня один?")

    def test_guide_texts_outnumber_model_probes(self):
        """Головна властивість режиму: інтервʼю веде гайд, не модель."""
        plan = phases.Plan(self.guide, coverage_detector=lambda t, x: [])
        state = phases.PhaseState()
        fixed = probes = 0
        for _ in range(60):
            action = plan.next_action(state, "Конкретна відповідь без узагальнень.", "текст")
            if action.kind == phases.WRAP_UP:
                break
            if action.kind == phases.FIXED:
                fixed += 1
            else:
                probes += 1
        self.assertGreater(fixed, probes)

    def test_topic_advances_after_probe_limit(self):
        self.reach_topics()                         # t1 питання 1
        labels = []
        for _ in range(6):
            action = self.step("Конкретна відповідь без узагальнень.")
            labels.append(action.label)
            if self.state.phase == phases.CLOSING:
                break
        self.assertIn("topic-level1", labels, "друга тема не почалась")

    def test_closing_questions_then_wrap_up(self):
        state = phases.PhaseState(phase=phases.CLOSING)
        first = self.plan.next_action(state, "щось", "")
        second = self.plan.next_action(state, "щось", "")
        final = self.plan.next_action(state, "щось", "")
        self.assertEqual(first.text, self.guide.closing_questions[0])
        self.assertEqual(second.text, self.guide.closing_questions[1])
        self.assertEqual(final.kind, phases.WRAP_UP)
        self.assertEqual(final.text, "Дякую.")

    def test_state_survives_round_trip(self):
        self.step("коротко")
        self.step("довга розповідь про все на світі")
        restored = phases.PhaseState.from_dict(self.state.to_dict())
        self.assertEqual(restored.phase, self.state.phase)
        self.assertEqual(restored.narrative_count, self.state.narrative_count)
        self.assertEqual(restored.hold_index, self.state.hold_index)


class TestCoverageFallback(unittest.TestCase):
    def test_lexical_fallback_when_detector_fails(self):
        """Падіння моделі не має означати, що всі теми питаються вдруге."""
        def broken(text, topics):
            raise RuntimeError("модель впала")
        plan = phases.Plan(guide(), coverage_detector=broken)
        found = plan.detect_coverage("Тут згадуються перша тема і щось перше кілька разів.")
        self.assertIsInstance(found, list)

    def test_detector_result_filtered_to_known_ids(self):
        plan = phases.Plan(guide(), coverage_detector=lambda t, x: ["t1", "вигадка"])
        self.assertEqual(plan.detect_coverage("текст"), ["t1"])

    def test_empty_narrative_covers_nothing(self):
        plan = phases.Plan(guide(), coverage_detector=lambda t, x: ["t1"])
        self.assertEqual(plan.detect_coverage(""), [])


class TestRealGuide(unittest.TestCase):
    """Справжній гайд дослідження подорожей — той, для чого будувався тул."""

    def setUp(self):
        self.space, self.guide = load_space_dir(TRAVEL)

    def test_guide_loads_with_all_parts(self):
        self.assertEqual(len(self.guide.topics), 10)
        self.assertTrue(self.guide.narrative_prompt)
        self.assertEqual(len(self.guide.closing_questions), 3)
        self.assertEqual(len(self.guide.deepening), 3)

    def test_every_topic_has_both_levels(self):
        for topic in self.guide.topics:
            self.assertTrue(topic.ask_if_missed, topic.id)
            self.assertTrue(topic.ask_for_detail, topic.id)
            self.assertTrue(topic.goal, topic.id)

    def test_full_run_reaches_closing_without_model(self):
        """Скільки реплік інтервʼю проходить, не питаючи модель узагалі."""
        plan = phases.Plan(self.guide, coverage_detector=lambda t, x: [])
        state = phases.PhaseState()
        fixed = probes = 0
        for _ in range(120):
            action = plan.next_action(state, "Конкретна відповідь без узагальнень.", "розповідь")
            if action.kind == phases.WRAP_UP:
                break
            if action.kind == phases.FIXED:
                fixed += 1
            else:
                probes += 1
        self.assertEqual(state.phase, phases.CLOSING)
        self.assertGreater(fixed, probes, "більшість реплік мусить бути з гайда, не від моделі")


if __name__ == "__main__":
    unittest.main()


class TestGapDriven(unittest.TestCase):
    """«Дізнатися все, що нам потрібно» — це пункти `must_learn` дослідника.

    Тема закривається не за лімітом ходів, а коли пункти закриті; а вільне
    уточнення націлене на конкретну незакриту прогалину, а не «щось по темі».
    """

    def setUp(self):
        self.guide = guide()
        self.plan = phases.Plan(self.guide, coverage_detector=lambda t, x: [])
        self.state = phases.PhaseState()
        self.plan.next_action(self.state, "коротко", "")
        self.plan.next_action(self.state, "Та все.", "")
        self.plan.next_action(self.state, "Та все, більше нічого.", "")   # → рівень 1

    def test_open_items_lists_unclosed(self):
        topic = self.guide.topics[0]
        self.assertEqual(phases.open_items(topic, self.state), [0])
        self.assertEqual(phases.focus_item(topic, self.state), "щось перше")

    def test_closed_item_removes_it_from_focus(self):
        topic = self.guide.topics[0]
        self.state.topic_items_done[topic.id] = [0]
        self.assertEqual(phases.open_items(topic, self.state), [])
        self.assertEqual(phases.focus_item(topic, self.state), "")

    def test_topic_closes_early_when_items_done(self):
        """Витрачати ходи на закриту тему означало б забрати їх у наступної."""
        topic = self.guide.topics[0]
        self.state.topic_items_done[topic.id] = [0]
        action = self.plan.next_action(self.state, "Конкретна відповідь.", "")
        self.assertEqual(action.label, "topic-level1")
        self.assertEqual(action.text, "Друге рівня один?")

    def test_probe_carries_the_focus_gap(self):
        wide = guide()
        wide.topics[0].max_probes = 4
        plan = phases.Plan(wide, coverage_detector=lambda t, x: [])
        state = phases.PhaseState()
        plan.next_action(state, "коротко", "")
        plan.next_action(state, "Та все.", "")
        plan.next_action(state, "Та все, більше нічого.", "")   # рівень 1
        plan.next_action(state, "Конкретна відповідь.", "")     # рівень 2
        action = plan.next_action(state, "Конкретна відповідь.", "")
        self.assertEqual(action.kind, phases.PROBE)
        self.assertEqual(action.focus, "щось перше")

    def test_items_state_survives_round_trip(self):
        self.state.topic_items_done["t1"] = [0]
        restored = phases.PhaseState.from_dict(self.state.to_dict())
        self.assertEqual(restored.topic_items_done["t1"], [0])


class TestHoldProducesNoTurn(unittest.TestCase):
    """Мовчання не має потрапляти в транскрипт порожнім ходом."""

    def setUp(self):
        from app.config.space import load_space_dir
        from app.interview.session import Session
        from app.providers.base import LLMProvider

        class Quiet(LLMProvider):
            name = "quiet"
            supports_structured = False

            def respond_text(self, system, messages):
                if "Відповідай ОДНИМ словом" in (messages[-1]["content"] if messages else ""):
                    return "ні"
                return "А що саме сталося?"

        self.space, self.guide = load_space_dir(TRAVEL)
        # Тримання розповіді — механіка вільного режиму: у сценарному темп
        # задає людина, і мовчання інтервʼюера там не існує.
        free_mode(self.guide)
        self.session = Session(self.space, self.guide, Quiet())

    def _pass_warmup(self, session):
        """Розігрів може доперепитати прогалину — проходимо його до кінця."""
        for _ in range(6):
            if session.phase_state.phase != phases.WARMUP:
                return
            session.answer("Їздили в Карпати, шість людей.")

    def test_hold_turn_is_empty_and_not_recorded(self):
        self.session.start()
        self._pass_warmup(self.session)                            # → narrative prompt
        before = len(self.session.turns)
        turn = self.session.answer("Довга розповідь про те, як усе починалось і що було далі.")
        self.assertEqual(turn.action, "hold")
        self.assertEqual(turn.utterance, "")
        # Додався лише хід респондента, репліки інтервʼюера немає.
        self.assertEqual(len(self.session.turns), before + 1)
        self.assertEqual(self.session.turns[-1]["role"], "respondent")

    def test_no_empty_interviewer_turns_in_transcript(self):
        self.session.start()
        for answer in ["Їздили в Карпати.", "Розповідь про підготовку і житло.",
                       "Ще деталі про квитки й бюджет."]:
            self.session.answer(answer)
        for turn in self.session.to_dict()["turns"]:
            self.assertTrue(turn["text"].strip(), "порожній хід у транскрипті")


class TestProgress(unittest.TestCase):
    """Прогрес мусить бути зрозумілим у КОЖНІЙ фазі.

    Раніше він рахувався по полю, яке в режимі сценарію не рухалось зовсім, —
    тому на екрані завжди стояло «Тема 1 з 10», навіть у фазі розповіді, де тем
    немає взагалі.
    """

    def setUp(self):
        self.guide = guide()
        self.plan = phases.Plan(self.guide, coverage_detector=lambda t, x: [])
        self.state = phases.PhaseState()

    def test_warmup_progress(self):
        info = self.plan.progress(self.state, asked=1)
        self.assertEqual(info["phase"], phases.WARMUP)
        self.assertEqual(info["label"], "Початок")

    def test_narrative_progress_has_no_part_numbers(self):
        """«Частина 1» пішла: вона нічого не означала.

        На питання «а буде частина 2?» відповіді не було — частин стільки,
        скільки людина захоче говорити. Рух у цій фазі показує чекліст тем.
        """
        self.plan.next_action(self.state, "коротко", "")          # → narrative
        first = self.plan.progress(self.state, asked=2)
        self.plan.next_action(self.state, "довга розповідь про поїздку", "")
        second = self.plan.progress(self.state, asked=2)

        self.assertEqual(first["section"], "Розповідь")
        self.assertNotIn("частина", first["section"])
        self.assertNotIn("частина", first["detail"])
        self.assertEqual(first["phase"], phases.NARRATIVE)
        # Розділ усе одно заповнюється — рух видно без числа.
        self.assertGreater(second["section_fraction"], first["section_fraction"])

    def test_topics_progress_names_the_topic(self):
        self.plan.next_action(self.state, "коротко", "")
        self.plan.next_action(self.state, "Та все.", "")
        self.plan.next_action(self.state, "Та все, більше нічого.", "")
        info = self.plan.progress(self.state, asked=4)
        self.assertEqual(info["section"], "Уточнення")
        self.assertIn("тема 1 з 2", info["detail"])
        self.assertIn(self.guide.topics[0].title, info["detail"])
        self.assertEqual(info["phase"], phases.TOPICS)

    def test_sections_are_the_real_structure(self):
        """Розділи — з гайда, а не зашиті: без вільної розповіді її й немає."""
        info = self.plan.progress(self.state, asked=1)
        self.assertEqual(info["sections"],
                         ["Початок", "Розповідь", "Уточнення", "Підсумок"])
        bare = phases.Plan(guide(narrative_prompt="", closing_questions=[]),
                           lambda text, topics: [])
        self.assertEqual(bare.progress(phases.PhaseState(), asked=1)["sections"],
                         ["Початок", "Уточнення"])

    def test_no_question_count_in_progress(self):
        """Числа питань у прогресі немає: «з 60» пугало й було неправдою."""
        info = self.plan.progress(self.state, asked=4)
        self.assertNotIn("max_questions", info)
        blob = " ".join([info["section"], info["detail"]])
        self.assertNotIn("60", blob)

    def test_closing_progress(self):
        state = phases.PhaseState(phase=phases.CLOSING)
        info = self.plan.progress(state, asked=9)
        self.assertEqual(info["section"], "Підсумок")
        self.assertEqual(info["section_index"], len(info["sections"]) - 1)
        self.assertIn("питання 1 з", info["detail"])

    def test_fraction_grows_monotonically_through_phases(self):
        seen = []
        state = phases.PhaseState()
        seen.append(self.plan.progress(state, 1)["fraction"])
        self.plan.next_action(state, "коротко", "")
        seen.append(self.plan.progress(state, 2)["fraction"])
        self.plan.next_action(state, "Та все.", "")
        self.plan.next_action(state, "Та все, більше нічого.", "")
        seen.append(self.plan.progress(state, 3)["fraction"])
        state.phase = phases.CLOSING
        seen.append(self.plan.progress(state, 9)["fraction"])
        self.assertEqual(seen, sorted(seen), "частка мусить лише зростати")

    def test_finish_narrative_jumps_to_topics(self):
        from app.config.space import load_space_dir
        from app.interview.session import Session
        from app.providers.base import LLMProvider

        class Quiet(LLMProvider):
            name = "quiet"
            supports_structured = False

            def respond_text(self, system, messages):
                return "ні"

        space, real_guide = load_space_dir(TRAVEL)
        free_mode(real_guide)
        session = Session(space, real_guide, Quiet())
        session.start()
        for _ in range(6):
            if session.phase_state.phase != phases.WARMUP:
                break
            session.answer("Їздили в Карпати.")                   # → narrative
        self.assertEqual(session.phase_state.phase, phases.NARRATIVE)
        session.answer("Коротка розповідь.", finish_narrative=True)
        self.assertEqual(session.phase_state.phase, phases.TOPICS)

    def test_finish_narrative_ignored_outside_narrative(self):
        from app.config.space import load_space_dir
        from app.interview.session import Session
        from app.providers.base import LLMProvider

        class Quiet(LLMProvider):
            name = "quiet"
            supports_structured = False

            def respond_text(self, system, messages):
                return "ні"

        space, real_guide = load_space_dir(TRAVEL)
        free_mode(real_guide)
        session = Session(space, real_guide, Quiet())
        session.start()
        session.answer("Їздили в Карпати.", finish_narrative=True)
        # Розповідь ще не починалась — прапорець не має нічого зламати. Фаза
        # лишається розігрівом, бо він доперепитує прогалину: оцінювач-заглушка
        # не зарахував нічого. Головне — що прапорець не перескочив фазу.
        self.assertEqual(session.phase_state.phase, phases.WARMUP)
        self.assertEqual(session.phase_state.narrative_count, 0)
