"""Сценарій гайда: розігрів → вільна розповідь → карта тем → підсумок.

Це найважливіший рушій інструменту: він веде інтервʼю дослівними формулюваннями
дослідника, модель не формулює жодного питання. Тому тестується без моделі
взагалі.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.space import Guide, Topic, load_space_dir
from app.interview import phases

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAVEL = os.path.join(ROOT, "spaces", "travel")


def guide(**kwargs):
    base = dict(
        key="g", goal="мета",
        topics=[
            Topic(id="t1", title="Перша тема", ask_if_missed="Питання рівня один?",
                  max_probes=2, must_learn=["щось перше"]),
            Topic(id="t2", title="Друга тема", ask_if_missed="Друге рівня один?",
                  max_probes=2, must_learn=["щось друге"]),
        ],
        opening="Розкажіть коротко.",
        closing="Дякую.",
        narrative_prompt="Розкажіть усю історію.",
        narrative_turns=3,
        narrative_holds=["Ага.", "І що далі?"],
        closing_questions=["Що забрало найбільше часу?", "Що муляло?"],
    )
    base.update(kwargs)
    return Guide(**base)


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

    def test_every_topic_has_one_question(self):
        for topic in self.guide.topics:
            self.assertTrue(topic.ask_if_missed, topic.id)
            self.assertTrue(topic.goal, topic.id)


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
        self.state.phase = phases.NARRATIVE
        self.state.narrative_count = 1
        first = self.plan.progress(self.state, asked=2)
        self.state.narrative_count = 2
        second = self.plan.progress(self.state, asked=2)

        self.assertEqual(first["section"], "Розповідь")
        self.assertNotIn("частина", first["section"])
        self.assertNotIn("частина", first["detail"])
        self.assertEqual(first["phase"], phases.NARRATIVE)
        # Розділ усе одно заповнюється — рух видно без числа.
        self.assertGreater(second["section_fraction"], first["section_fraction"])

    def test_topics_progress_names_the_topic(self):
        self.state.phase = phases.TOPICS
        self.state.topic_index = 0
        info = self.plan.progress(self.state, asked=4)
        self.assertEqual(info["section"], "Теми")
        self.assertIn("тема 1 з 2", info["detail"])
        self.assertIn(self.guide.topics[0].title, info["detail"])
        self.assertEqual(info["phase"], phases.TOPICS)

    def test_sections_are_the_real_structure(self):
        """Розділи — з гайда, а не зашиті: без вільної розповіді її й немає."""
        info = self.plan.progress(self.state, asked=1)
        self.assertEqual(info["sections"],
                         ["Початок", "Розповідь", "Теми", "Підсумок"])
        bare = phases.Plan(guide(narrative_prompt="", closing_questions=[]),
                           lambda text, topics: [])
        self.assertEqual(bare.progress(phases.PhaseState(), asked=1)["sections"],
                         ["Початок", "Теми"])

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
        state.phase = phases.NARRATIVE
        state.narrative_count = 1
        seen.append(self.plan.progress(state, 2)["fraction"])
        state.phase = phases.TOPICS
        state.topic_index = 0
        seen.append(self.plan.progress(state, 3)["fraction"])
        state.phase = phases.CLOSING
        seen.append(self.plan.progress(state, 9)["fraction"])
        self.assertEqual(seen, sorted(seen), "частка мусить лише зростати")


if __name__ == "__main__":
    unittest.main()
