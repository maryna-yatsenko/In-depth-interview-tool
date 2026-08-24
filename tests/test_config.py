"""Конфіг: падати на старті краще, ніж посеред інтервʼю."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.space import ConfigError, load_guide, load_space, load_space_dir

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "spaces", "example")


def write(tmp, name, data):
    path = os.path.join(tmp, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    return path


class TestConfig(unittest.TestCase):
    def test_example_space_loads(self):
        space, guide = load_space_dir(EXAMPLE)
        self.assertEqual(space.primary_language, space.languages[0])
        self.assertTrue(guide.topics)

    def test_missing_persona_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, "space.json", {"key": "x", "title": "X", "languages": ["uk"]})
            with self.assertRaises(ConfigError):
                load_space(p)

    def test_empty_languages_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, "space.json", {"key": "x", "title": "X", "languages": [],
                                          "persona": {"self_intro": "привіт"}})
            with self.assertRaises(ConfigError):
                load_space(p)

    def test_deidentify_without_rules_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, "space.json", {
                "key": "x", "title": "X", "languages": ["uk"],
                "persona": {"self_intro": "привіт"},
                "privacy": {"deidentify": True, "never_ask_about": []},
            })
            with self.assertRaises(ConfigError):
                load_space(p)

    def test_duplicate_topic_id_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, "g.json", {"key": "g", "goal": "мета", "topics": [
                {"id": "a", "title": "A"}, {"id": "a", "title": "B"}]})
            with self.assertRaises(ConfigError):
                load_guide(p)

    def test_unknown_interface_mode_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, "space.json", {
                "key": "x", "title": "X", "languages": ["uk"],
                "persona": {"self_intro": "привіт"},
                "interface": {"mode": "телепатія"},
            })
            with self.assertRaises(ConfigError) as ctx:
                load_space(p)
            self.assertIn("interface.mode", str(ctx.exception))

    def test_voice_mode_without_stt_rejected(self):
        """Голосовий режим без розпізнавання = екран, на якому нічого не сказати."""
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, "space.json", {
                "key": "x", "title": "X", "languages": ["uk"],
                "persona": {"self_intro": "привіт"},
                "interface": {"mode": "voice"},
                "providers": {"stt": {"provider": "none"}},
            })
            with self.assertRaises(ConfigError):
                load_space(p)

    def test_voice_mode_with_stt_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, "space.json", {
                "key": "x", "title": "X", "languages": ["uk"],
                "persona": {"self_intro": "привіт"},
                "interface": {"mode": "voice"},
                "providers": {"stt": {"provider": "browser"}},
            })
            space = load_space(p)
            self.assertEqual(space.interface["mode"], "voice")

    def test_autoplay_defaults_to_off(self):
        """Питання первинно текстом: голос вмикає респондент, а не сторінка."""
        space, _ = load_space_dir(EXAMPLE)
        self.assertFalse(space.interface.get("autoplay", False))

    def test_autoplay_must_be_boolean(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, "space.json", {
                "key": "x", "title": "X", "languages": ["uk"],
                "persona": {"self_intro": "привіт"},
                "interface": {"mode": "text", "autoplay": "так"},
            })
            with self.assertRaises(ConfigError) as ctx:
                load_space(p)
            self.assertIn("autoplay", str(ctx.exception))

    def test_expected_words_defaults(self):
        space, _ = load_space_dir(EXAMPLE)
        self.assertGreaterEqual(space.interface.get("expected_words", 15), 1)

    def test_expected_words_must_be_positive_integer(self):
        for bad in ["багато", 0, -3, 2.5]:
            with tempfile.TemporaryDirectory() as tmp:
                p = write(tmp, "space.json", {
                    "key": "x", "title": "X", "languages": ["uk"],
                    "persona": {"self_intro": "привіт"},
                    "interface": {"mode": "text", "expected_words": bad},
                })
                with self.assertRaises(ConfigError, msg=repr(bad)):
                    load_space(p)

    def test_default_mode_is_text(self):
        space, _ = load_space_dir(EXAMPLE)
        self.assertIn(space.interface.get("mode", "text"), ("voice", "text"))

    def test_unknown_guide_key_lists_available(self):
        with self.assertRaises(ConfigError) as ctx:
            load_space_dir(EXAMPLE, "не-існує")
        self.assertIn("first", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

class TestRespondentWording(unittest.TestCase):
    """Дві аудиторії — дві назви теми.

    `title` — карта дослідника, вона мусить збігатися з паперовим гайдом і
    лишатись у звітах. `shown_as` — те, що читає респондент: «Розбіжна
    інформація» й «Розбіжність поглядів» для людини виглядають однаково й не
    означають нічого.
    """

    def test_label_falls_back_to_title(self):
        from app.config.space import Topic
        self.assertEqual(Topic(id="x", title="Гроші").label, "Гроші")

    def test_label_prefers_respondent_wording(self):
        from app.config.space import Topic
        topic = Topic(id="x", title="Розбіжна інформація",
                      shown_as="Коли в різних людей були різні дані")
        self.assertEqual(topic.label, "Коли в різних людей були різні дані")
        # Фахова назва нікуди не зникає: звіти читає дослідник.
        self.assertEqual(topic.title, "Розбіжна інформація")

    def test_travel_guide_speaks_human(self):
        """У робочому просторі формулювання для людини задані на всі теми."""
        from app.config.space import load_space_dir
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _, guide = load_space_dir(os.path.join(root, "spaces", "travel"))
        for topic in guide.topics:
            self.assertTrue(topic.shown_as,
                            "тема «%s» без формулювання для респондента" % topic.title)
            self.assertNotEqual(topic.shown_as, topic.title)

