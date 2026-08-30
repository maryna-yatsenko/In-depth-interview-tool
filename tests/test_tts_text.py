"""Нормалізація тексту для символьної моделі.

Причина існування цього файла: алфавіт моделі не має ні цифр, ні латиниці, ні
великих літер, і вони зникають БЕЗ помилки. «Це було у 2019 році» звучить рівно
як «Це було у році». Тихо зламане питання гірше за помилку.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.providers.tts_text import APO, normalize, number_to_words


class TestNumerals(unittest.TestCase):
    def test_units_and_teens(self):
        self.assertEqual(number_to_words(0), "нуль")
        self.assertEqual(number_to_words(1), "один")
        self.assertEqual(number_to_words(5), "п" + APO + "ять")
        self.assertEqual(number_to_words(11), "одинадцять")
        self.assertEqual(number_to_words(19), "дев" + APO + "ятнадцять")

    def test_tens_and_hundreds(self):
        self.assertEqual(number_to_words(20), "двадцять")
        self.assertEqual(number_to_words(21), "двадцять один")
        self.assertEqual(number_to_words(100), "сто")
        self.assertEqual(number_to_words(101), "сто один")
        self.assertEqual(number_to_words(999), "дев" + APO + "ятсот дев" + APO + "яносто дев" + APO + "ять")

    def test_thousands_use_feminine_and_correct_plural(self):
        """«одна тисяча», «дві тисячі», «п'ять тисяч» — форми різні."""
        self.assertEqual(number_to_words(1000), "одна тисяча")
        self.assertEqual(number_to_words(2000), "дві тисячі")
        self.assertEqual(number_to_words(5000), "п" + APO + "ять тисяч")
        self.assertEqual(number_to_words(2019), "дві тисячі дев" + APO + "ятнадцять")

    def test_millions(self):
        self.assertEqual(number_to_words(1000000), "один мільйон")
        self.assertIn("мільйон", number_to_words(1250000))
        self.assertIn("тисяч", number_to_words(1250000))

    def test_negative(self):
        self.assertTrue(number_to_words(-5).startswith("мінус"))

    def test_apostrophe_is_ascii(self):
        """Модель знає лише ASCII-апостроф; типографський «ʼ» вона не вимовить."""
        word = number_to_words(5)
        self.assertIn("'", word)
        self.assertNotIn("ʼ", word)
        self.assertNotIn("’", word)


class TestNormalize(unittest.TestCase):
    def test_digits_become_words(self):
        out, report = normalize("Це було у 2019 році.")
        self.assertNotRegex(out, r"\d")
        self.assertIn("дві тисячі", out)
        self.assertEqual(report["numbers"], ["2019"])

    def test_uppercase_lowered(self):
        out, _ = normalize("РОЗКАЖІТЬ ПРО ЦЕ.")
        self.assertEqual(out, "розкажіть про це.")

    def test_latin_transliterated_not_dropped(self):
        out, report = normalize("Ви бачили LIGA?")
        self.assertIn("ліга", out)
        self.assertEqual(report["latin"], ["LIGA"])

    def test_thousand_separator_joined(self):
        out, _ = normalize("Коштувало 15 000 гривень.")
        self.assertIn("п" + APO + "ятнадцять тисяч", out)
        self.assertNotIn("нуль", out)

    def test_big_thousand_separator(self):
        out, _ = normalize("Оборот 1 250 000 гривень.")
        self.assertIn("мільйон", out)

    def test_leading_zero_group_not_joined(self):
        """«067 123» — це телефон, а не число: склеювати не можна."""
        out, _ = normalize("Телефон 067 123.")
        self.assertNotIn("тисяч", out)

    def test_separate_single_digits_not_joined(self):
        out, _ = normalize("Було 2 3 окремо.")
        self.assertIn("два три", out)

    def test_typographic_apostrophe_normalized(self):
        out, _ = normalize("це п’ять")
        self.assertIn("п'ять", out)
        self.assertNotIn("’", out)

    def test_quotes_and_ellipsis_removed(self):
        out, _ = normalize("Це «складно» і ще…")
        self.assertNotIn("«", out)
        self.assertNotIn("…", out)

    def test_unknown_characters_reported_not_silently_dropped(self):
        out, report = normalize("Ціна 100€ або 50£")
        self.assertTrue(report["dropped"], "невідомі символи мусять потрапити у звіт")
        self.assertIn("€", report["dropped"])

    def test_empty_input(self):
        out, report = normalize("")
        self.assertEqual(out, "")
        self.assertEqual(report["numbers"], [])

    def test_result_uses_only_model_alphabet(self):
        """Головна гарантія: на виході немає нічого, чого модель не знає."""
        import json
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config = os.path.join(root, "local", "models", "uk_UA-ukrainian_tts-medium.onnx.json")
        if not os.path.isfile(config):
            self.skipTest("немає моделі для перевірки алфавіту")
        with open(config, encoding="utf-8") as fh:
            allowed = set(json.load(fh)["phoneme_id_map"].keys())

        sample = "Ви бачили LIGA360 у 2019 році? Коштувало 15 000 грн — «дорого»…"
        out, _ = normalize(sample)
        unknown = sorted({ch for ch in out if ch not in allowed})
        self.assertEqual(unknown, [], "у вивід просочились символи поза алфавітом моделі")


if __name__ == "__main__":
    unittest.main()


class TestStress(unittest.TestCase):
    """Наголоси — головний важіль якості української вимови: модель навчена їх
    читати, і без них частина слів звучить неправильно."""

    def setUp(self):
        from app.providers.tts_text import stress_available
        if not stress_available():
            self.skipTest("розставляч наголосів не встановлений")

    def test_stress_marks_added(self):
        from app.providers.tts_text import STRESS_MARK
        out, report = normalize("Розкажіть, будь ласка, про останній випадок.", add_stress=True)
        self.assertTrue(report["stressed"])
        self.assertIn(STRESS_MARK, out)
        self.assertGreaterEqual(out.count(STRESS_MARK), 3)

    def test_expanded_numbers_also_get_stress(self):
        """Числа розкриваються ДО наголосів — інакше «дві тисячі» лишиться без них."""
        from app.providers.tts_text import STRESS_MARK
        out, _ = normalize("Це було у 2019 році.", add_stress=True)
        self.assertIn("ти" + STRESS_MARK + "сячі", out)

    def test_stress_off_by_default(self):
        from app.providers.tts_text import STRESS_MARK
        out, report = normalize("Розкажіть про випадок.")
        self.assertNotIn(STRESS_MARK, out)
        self.assertFalse(report["stressed"])

    def test_stress_mark_survives_alphabet_filter(self):
        """Знак наголосу мусить пройти фільтр невідомих символів — він у алфавіті."""
        from app.providers.tts_text import STRESS_MARK
        out, report = normalize("Останній випадок.", add_stress=True)
        self.assertIn(STRESS_MARK, out)
        self.assertNotIn(STRESS_MARK, report["dropped"])

    def test_output_still_within_model_alphabet(self):
        import json
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config = os.path.join(root, "local", "models", "uk_UA-ukrainian_tts-medium.onnx.json")
        if not os.path.isfile(config):
            self.skipTest("немає моделі")
        with open(config, encoding="utf-8") as fh:
            allowed = set(json.load(fh)["phoneme_id_map"].keys())
        out, _ = normalize("Ви бачили LIGA360 у 2019 році? Коштувало 15 000 грн.", add_stress=True)
        unknown = sorted({ch for ch in out if ch not in allowed})
        self.assertEqual(unknown, [])
