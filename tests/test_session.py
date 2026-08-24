"""Ядро: модель пропонує, код вирішує. Тести саме на «код вирішує»."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.space import load_space_dir
from app.interview.session import Session
from app.providers.base import LLMProvider

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "spaces", "example")


class ScriptedLLM(LLMProvider):
    """Провайдер, що віддає заздалегідь задані ходи — так перевіряються правила."""

    name = "scripted"
    supports_system_turns = True

    def __init__(self, script):
        self.script = list(script)
        self.seen_messages = []

    def respond_json(self, system, messages, schema, max_tokens=2000):
        self.seen_messages.append(messages)
        return self.script.pop(0) if self.script else {
            "utterance": "Що сталося потім?", "topic_id": "", "action": "probe", "coverage_note": ""
        }


def turn(utterance="Що ви зробили далі?", action="probe", topic_id="", note="ok"):
    return {"utterance": utterance, "topic_id": topic_id, "action": action, "coverage_note": note}


class TestSession(unittest.TestCase):
    def setUp(self):
        self.space, self.guide = load_space_dir(EXAMPLE)

    def _session(self, script):
        return Session(self.space, self.guide, ScriptedLLM(script))

    def test_probe_limit_forces_topic_change(self):
        first = self.guide.topics[0]
        s = self._session([turn() for _ in range(first.max_probes + 2)])
        s.start()
        overrides = []
        for _ in range(first.max_probes + 1):
            t = s.answer("щось відповів")
            if t.override:
                overrides.append(t.override)
        self.assertTrue(any("ліміт уточнень" in o for o in overrides),
                        "ядро не форсувало перехід після ліміту уточнень")

    def test_wrap_up_rejected_while_topics_remain(self):
        s = self._session([turn(action="wrap_up")])
        s.start()
        t = s.answer("коротко")
        self.assertNotEqual(t.action, "wrap_up", "модель завершила інтервʼю з непокритими темами")
        self.assertIn("непокритими темами", t.override or "")

    def test_guard_rejection_triggers_retry_then_fallback(self):
        bad = turn(utterance="Ви абсолютно праві, це незручно. Вам не вистачає фільтра?")
        s = self._session([bad, bad, bad])
        s.start()
        t = s.answer("так, незручно")
        self.assertTrue(t.fallback_used, "після трьох порушень не спрацювала відступна репліка")
        self.assertEqual(len(t.guard_rejections), 3)
        self.assertEqual(s.turns[-1]["text"], t.utterance)
        self.assertNotIn("праві", s.turns[-1]["text"])

    def test_bad_utterance_never_enters_transcript(self):
        bad = turn(utterance="Чудово! Вам не вистачає фільтра?")
        s = self._session([bad, turn(utterance="Що ви зробили далі?")])
        s.start()
        s.answer("відповідь")
        texts = " ".join(t["text"] for t in s.turns)
        self.assertNotIn("Чудово", texts)

    def test_max_turns_forces_wrap_up(self):
        self.guide.max_turns = 3
        s = self._session([turn() for _ in range(6)])
        s.start()
        actions = []
        while not s.done and len(actions) < 6:
            actions.append(s.answer("щось").action)
        self.assertTrue(s.done, "ліміт реплік не завершив інтервʼю")
        self.assertEqual(actions[-1], "wrap_up")

    def test_forced_wrap_up_uses_closing_not_a_question(self):
        self.guide.max_turns = 2
        s = self._session([turn(), turn()])
        s.start()
        t = s.answer("щось")
        while not s.done:
            t = s.answer("щось")
        self.assertEqual(t.utterance, self.guide.closing)

    def test_state_goes_as_system_turn_when_supported(self):
        s = self._session([turn()])
        s.start()
        s.answer("відповідь")
        last = s.llm.seen_messages[-1][-1]
        self.assertEqual(last["role"], "system")
        self.assertIn("СЛУЖБОВИЙ СТАН", last["content"])

    def test_state_merges_into_user_turn_when_unsupported(self):
        llm = ScriptedLLM([turn()])
        llm.supports_system_turns = False
        s = Session(self.space, self.guide, llm)
        s.start()
        s.answer("відповідь")
        last = llm.seen_messages[-1][-1]
        self.assertEqual(last["role"], "user")
        self.assertIn("СЛУЖБОВИЙ СТАН", last["content"])

    def test_from_dict_restores_position_and_probes(self):
        s = self._session([turn(), turn(), turn()])
        s.start()
        s.answer("раз")
        s.answer("два")
        data = s.to_dict()

        restored = Session.from_dict(self.space, self.guide, ScriptedLLM([turn()]), data)
        self.assertEqual(restored.session_id, s.session_id)
        self.assertEqual(restored.topic_index, s.topic_index)
        self.assertEqual(restored.probes, s.probes)
        self.assertEqual(len(restored.turns), len(s.turns))
        self.assertEqual(restored.started_at, s.started_at)

    def test_from_dict_rejects_other_prompt_version(self):
        s = self._session([turn()])
        s.start()
        data = s.to_dict()
        data["prompt_version"] = "interviewer.v0"
        with self.assertRaises(ValueError) as ctx:
            Session.from_dict(self.space, self.guide, ScriptedLLM([]), data)
        self.assertIn("методолог", str(ctx.exception))

    def test_from_dict_rejects_other_guide(self):
        s = self._session([turn()])
        s.start()
        data = s.to_dict()
        data["guide"] = "інший-гайд"
        with self.assertRaises(ValueError):
            Session.from_dict(self.space, self.guide, ScriptedLLM([]), data)

    def test_transcript_records_provenance(self):
        s = self._session([turn(action="wrap_up")])
        s.start()
        s.answer("щось")
        d = s.to_dict()
        for key in ("prompt_version", "llm_provider", "space", "guide", "incidents"):
            self.assertIn(key, d)


if __name__ == "__main__":
    unittest.main()
