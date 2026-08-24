"""Деідентифікація: головний ризик тут — не «не спіймали», а «з'їли зайве».

Замаскований фрагмент не відновити. Тому половина тестів нижче — про те, що
інструмент НЕ чіпає: роки, ціни, дати, вік, перелічування. Тихо втрачені дані
дослідження гірші за незамасковану пошту, бо про них ніхто не дізнається.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.space import ConfigError, Privacy, SpaceConfig, Persona, load_space_dir
from app.interview.deidentify import Deidentifier
from app.interview.session import Session
from app.providers.base import LLMProvider

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "spaces", "example")


class TestDeidentifier(unittest.TestCase):
    def setUp(self):
        self.d = Deidentifier(enabled=True)

    def scrub(self, text):
        return self.d.scrub(text)[0]

    # ── що мусить маскуватись ────────────────────────────────────────────
    def test_email_masked(self):
        self.assertEqual(self.scrub("пишіть на a.b@c.com."), "пишіть на [ПОШТА].")

    def test_url_masked(self):
        self.assertIn("[ПОСИЛАННЯ]", self.scrub("дивіться https://example.com/x?y=1 там"))

    def test_formatted_phone_masked(self):
        for text in ["+38 (067) 123-45-67", "067-123-45-67", "(044) 123 45 67"]:
            self.assertIn("[ТЕЛЕФОН]", self.scrub("номер " + text), text)

    def test_long_digit_run_masked(self):
        self.assertIn("[ЧИСЛО]", self.scrub("код 12345678 у довідці"))
        self.assertIn("[ЧИСЛО]", self.scrub("записуйте 0671234567"))

    # ── що НЕ мусить чіпатись (найважливіше) ─────────────────────────────
    def test_years_sequence_untouched(self):
        """Регресія: попередній шаблон з'їдав це як телефон."""
        text = "Це було у 2019 2020 2021 2022 роках."
        self.assertEqual(self.scrub(text), text)

    def test_prices_untouched(self):
        text = "Ціна впала з 1200 до 950, потім до 800 гривень."
        self.assertEqual(self.scrub(text), text)

    def test_dates_untouched(self):
        text = "Це було 12.03.2024, а потім 15.04.2024."
        self.assertEqual(self.scrub(text), text)

    def test_enumeration_untouched(self):
        text = "По 3 4 5 6 7 8 9 одиниць у партії."
        self.assertEqual(self.scrub(text), text)

    def test_short_numbers_untouched(self):
        text = "Мені 34 роки, працюю 5 років, маю 2 велосипеди."
        self.assertEqual(self.scrub(text), text)

    # ── вимкнений режим ──────────────────────────────────────────────────
    def test_disabled_changes_nothing(self):
        off = Deidentifier(enabled=False)
        text = "пошта a@b.com і номер 0671234567"
        self.assertEqual(off.scrub(text), (text, []))

    # ── шаблони простору ─────────────────────────────────────────────────
    def test_space_pattern_wins_over_builtin(self):
        """Конкретніше правило простору мусить спрацювати раніше, ніж загальне
        «8+ цифр» з'їсть його під виглядом [ЧИСЛО]."""
        d = Deidentifier(enabled=True, extra_patterns=[
            {"name": "order", "pattern": r"замовлення\s+\d{8,}", "replacement": "[ЗАМОВЛЕННЯ]"}
        ])
        out, hits = d.scrub("оформив замовлення 12345678 у березні")
        self.assertIn("[ЗАМОВЛЕННЯ]", out)
        self.assertNotIn("[ЧИСЛО]", out)
        self.assertEqual(hits[0]["rule"], "order")

    def test_broken_space_pattern_raises_early(self):
        with self.assertRaises(ValueError):
            Deidentifier(enabled=True, extra_patterns=[{"name": "bad", "pattern": "([unclosed"}])

    def test_builtin_can_be_disabled(self):
        d = Deidentifier(enabled=True, use_builtin=False,
                         extra_patterns=[{"name": "x", "pattern": r"секрет", "replacement": "[X]"}])
        out, _ = d.scrub("секрет і пошта a@b.com")
        self.assertIn("[X]", out)
        self.assertIn("a@b.com", out, "вбудовані шаблони не вимкнулись")

    def test_hits_report_rule_and_count(self):
        _, hits = self.d.scrub("a@b.com і c@d.com")
        self.assertEqual(hits, [{"rule": "email", "count": 2}])


class TestConfigValidation(unittest.TestCase):
    def test_uncompilable_pattern_rejected_at_load(self):
        """Впасти на старті, а не на першій репліці респондента."""
        from app.config.space import load_space
        import json, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "space.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({
                    "key": "x", "title": "X", "languages": ["uk"],
                    "persona": {"self_intro": "привіт"},
                    "privacy": {"deidentify": True, "never_ask_about": ["щось"],
                                "patterns": [{"name": "bad", "pattern": "([unclosed"}]},
                }, fh)
            with self.assertRaises(ConfigError) as ctx:
                load_space(path)
            self.assertIn("не компілюється", str(ctx.exception))

    def test_masking_that_does_nothing_is_rejected(self):
        from app.config.space import load_space
        import json, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "space.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({
                    "key": "x", "title": "X", "languages": ["uk"],
                    "persona": {"self_intro": "привіт"},
                    "privacy": {"deidentify": True, "never_ask_about": ["щось"],
                                "use_builtin_patterns": False, "patterns": []},
                }, fh)
            with self.assertRaises(ConfigError):
                load_space(path)


class ScriptedLLM(LLMProvider):
    name = "scripted"
    supports_system_turns = True

    def __init__(self):
        self.seen = []

    def respond_json(self, system, messages, schema, max_tokens=2000):
        self.seen.append(messages)
        return {"utterance": "Що ви зробили далі?", "topic_id": "", "action": "probe",
                "coverage_note": "ok"}


class TestSessionIntegration(unittest.TestCase):
    def test_model_never_sees_raw_personal_data(self):
        """Суть рішення «маскувати на вході»: у вендора не має бути сирого тексту."""
        space, guide = load_space_dir(EXAMPLE)
        llm = ScriptedLLM()
        session = Session(space, guide, llm)
        session.start()
        session.answer("Мій контакт maryna@example.com, дзвоніть 067-123-45-67.")

        sent = str(llm.seen[-1])
        self.assertNotIn("maryna@example.com", sent)
        self.assertNotIn("067-123-45-67", sent)
        self.assertIn("[ПОШТА]", sent)

    def test_transcript_records_what_was_masked(self):
        space, guide = load_space_dir(EXAMPLE)
        session = Session(space, guide, ScriptedLLM())
        session.start()
        session.answer("пишіть на a@b.com")
        respondent_turn = [t for t in session.turns if t["role"] == "respondent"][0]
        self.assertIn("masked", respondent_turn)
        self.assertEqual(respondent_turn["masked"][0]["rule"], "email")
        kinds = [i["kind"] for i in session.incidents]
        self.assertIn("deidentified", kinds)

    def test_no_masking_marker_when_nothing_matched(self):
        space, guide = load_space_dir(EXAMPLE)
        session = Session(space, guide, ScriptedLLM())
        session.start()
        session.answer("Просто хотів велосипед, нічого особливого.")
        respondent_turn = [t for t in session.turns if t["role"] == "respondent"][0]
        self.assertNotIn("masked", respondent_turn)


if __name__ == "__main__":
    unittest.main()
