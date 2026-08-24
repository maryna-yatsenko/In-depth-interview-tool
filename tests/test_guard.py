"""Guard — код, що гарантує те, про що просить промпт. Тести на кожне правило."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.interview.guard import check, check_turn


class TestGuard(unittest.TestCase):
    def test_clean_probe_passes(self):
        self.assertEqual(check("Що ви зробили далі?"), [])
        self.assertEqual(check("Розкажіть про останній раз, коли це сталося."), [])

    def test_two_questions_rejected(self):
        self.assertTrue(any("більше одного питання" in p for p in check("Як? І чому?")))

    def test_agreement_rejected_with_adverb(self):
        # Прислівник між словами колись ламав перевірку підстрокою.
        for phrase in ["Ви праві.", "Ви абсолютно праві.", "Ви маєте цілком рацію.", "Вы правы."]:
            self.assertTrue(check(phrase), "не спіймано погоджування: %s" % phrase)

    def test_evaluation_rejected(self):
        for phrase in ["Чудово, розкажіть далі.", "Дуже цікаво.", "Я вас розумію."]:
            self.assertTrue(check(phrase), "не спіймано оцінку: %s" % phrase)

    def test_leading_question_rejected(self):
        self.assertTrue(check("Вам не вистачає фільтра?"))
        self.assertTrue(check("Чи не здається вам це складним?"))
        self.assertTrue(check("Тобто вам важлива швидкість?"))

    def test_hypothetical_rejected(self):
        self.assertTrue(check("А якби у вас була така функція?"))
        self.assertTrue(check("Уявіть, що цього немає."))

    def test_reproach_rejected(self):
        self.assertTrue(check("Чому ви не скористалися пошуком?"))

    def test_mention_of_others_rejected(self):
        self.assertTrue(check("Більшість користувачів роблять інакше."))

    def test_too_long_rejected(self):
        self.assertTrue(any("задовга" in p for p in check("а" * 400)))

    def test_empty_rejected(self):
        self.assertTrue(check("   "))

    def test_domain_term_first_named_by_interviewer_rejected(self):
        turns = [{"role": "respondent", "text": "Я просто хотів велосипед."}]
        problems = check_turn("Вас цікавив гравел?", ["гравел"], turns)
        self.assertTrue(any("гравел" in p for p in problems))

    def test_domain_term_allowed_after_respondent_used_it(self):
        turns = [{"role": "respondent", "text": "Мені радили взяти гравел."}]
        self.assertEqual(check_turn("Що вам сказали про гравел?", ["гравел"], turns), [])

    def test_digits_rejected_when_channel_needs_words(self):
        """Символьна модель губить цифри без помилки — тому їх ловить guard."""
        problems = check("Що було у 2019 році?", require_spoken_form=True)
        self.assertTrue(any("цифри" in p for p in problems))

    def test_latin_rejected_when_channel_needs_words(self):
        problems = check("Ви бачили LIGA?", require_spoken_form=True)
        self.assertTrue(any("латиниця" in p for p in problems))

    def test_digits_allowed_when_channel_does_not_care(self):
        """У текстовому каналі цифри — не проблема, і забороняти їх не треба."""
        self.assertEqual(check("Що було у 2019 році?"), [])

    def test_spoken_form_words_pass(self):
        self.assertEqual(
            check("Що було у дві тисячі дев'ятнадцятому році?", require_spoken_form=True), [])

    def test_no_false_positive_on_neutral_you_question(self):
        self.assertEqual(check("Ви користувались цим у роботі?"), [])


if __name__ == "__main__":
    unittest.main()


class TestRepetition(unittest.TestCase):
    """Повторити питання — сказати людині, що її не слухали. Слабкі моделі
    роблять це особливо охоче: зачіпаються за опис теми й повертають ту саму
    фразу щоходу (виявлено на локальній моделі 21.08.2026)."""

    def _turns(self, *texts):
        return [{"role": "interviewer", "text": t} for t in texts]

    def test_exact_repeat_rejected(self):
        turns = self._turns("Що стало поштовхом купити велосипед?")
        problems = check_turn("Що стало поштовхом купити велосипед?", [], turns)
        self.assertTrue(any("вже ставилось" in p for p in problems))

    def test_reworded_repeat_rejected(self):
        """Порівнюємо набори слів, а не рядки: те саме питання іншими словами."""
        turns = self._turns("Що стало поштовхом купити велосипед?")
        problems = check_turn("Що стало поштовхом, щоб купити велосипед?", [], turns)
        self.assertTrue(any("вже ставилось" in p for p in problems))

    def test_different_question_passes(self):
        turns = self._turns("Що стало поштовхом купити велосипед?")
        self.assertEqual(check_turn("Яку модель він вам порадив?", [], turns), [])

    def test_short_probe_not_treated_as_repeat(self):
        """«Що ви зробили далі?» — робоче уточнення, воно може повторюватись
        у різних темах, і блокувати його було б шкідливо."""
        turns = self._turns("Що ви зробили далі?")
        problems = check_turn("Що сталося потім?", [], turns)
        self.assertEqual(problems, [])

    def test_respondent_turns_ignored(self):
        turns = [{"role": "respondent", "text": "Я купив велосипед у березні."}]
        self.assertEqual(check_turn("Я купив велосипед у березні?", [], turns), [])
