"""Банк реплік: інтервʼюер говорить лише тим, що людина переглянула й записала.

У цьому режимі банк — це і є методологія. Тому тести стежать за двома речами:
щоб зламаний банк не доїхав до респондента, і щоб модель не могла сказати
нічого поза набором.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.phrases import PhraseBank, PhraseError, load_bank, save_bank
from app.config.space import load_space_dir
from app.interview.session import Session
from app.providers.base import LLMProvider

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "spaces", "example")


def write_bank(directory, phrases, with_audio=()):
    os.makedirs(os.path.join(directory, "audio"), exist_ok=True)
    for name in with_audio:
        with open(os.path.join(directory, "audio", name), "wb") as fh:
            fh.write(b"RIFFfake")
    save_bank(directory, phrases)


class TestLoad(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_file_gives_empty_bank(self):
        bank = load_bank(self.tmp)
        self.assertEqual(bank.phrases, [])

    def test_duplicate_id_rejected(self):
        write_bank(self.tmp, [
            {"id": "a", "kind": "probe", "text": "раз"},
            {"id": "a", "kind": "probe", "text": "два"},
        ])
        with self.assertRaises(PhraseError):
            load_bank(self.tmp)

    def test_unknown_kind_rejected(self):
        write_bank(self.tmp, [{"id": "a", "kind": "жарт", "text": "текст"}])
        with self.assertRaises(PhraseError) as ctx:
            load_bank(self.tmp)
        self.assertIn("Допустимі", str(ctx.exception))

    def test_empty_text_rejected(self):
        write_bank(self.tmp, [{"id": "a", "kind": "probe", "text": "  "}])
        with self.assertRaises(PhraseError):
            load_bank(self.tmp)

    def test_topic_phrase_without_topic_rejected(self):
        write_bank(self.tmp, [{"id": "a", "kind": "topic", "text": "текст"}])
        with self.assertRaises(PhraseError):
            load_bank(self.tmp)

    def test_audio_name_with_path_rejected(self):
        """Ім'я файла йде у шлях — переходи по теках недопустимі."""
        write_bank(self.tmp, [
            {"id": "a", "kind": "probe", "text": "текст", "audio": "../../secret.wav"}])
        with self.assertRaises(PhraseError):
            load_bank(self.tmp)

    def test_missing_audio_file_means_unrecorded_not_error(self):
        """Запис могли видалити руками — це не поломка, це «не записано»."""
        write_bank(self.tmp, [
            {"id": "a", "kind": "probe", "text": "текст", "audio": "нема.wav"}])
        bank = load_bank(self.tmp)
        self.assertFalse(bank.by_id("a").recorded)


class TestGaps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_gaps_name_what_is_missing(self):
        write_bank(self.tmp, [{"id": "p1", "kind": "probe", "text": "текст"}])
        gaps = load_bank(self.tmp).missing_for_interview(["t1"])
        joined = " ".join(gaps)
        self.assertIn("відкриття", joined)
        self.assertIn("завершення", joined)
        self.assertIn("t1", joined)

    def test_complete_bank_has_no_gaps(self):
        write_bank(self.tmp, [
            {"id": "open", "kind": "opening", "text": "привіт", "audio": "open.wav"},
            {"id": "close", "kind": "closing", "text": "дякую", "audio": "close.wav"},
            {"id": "p1", "kind": "probe", "text": "далі?", "audio": "p1.wav"},
            {"id": "t1q", "kind": "topic", "topic_id": "t1", "text": "про тему",
             "audio": "t1q.wav"},
        ], with_audio=["open.wav", "close.wav", "p1.wav", "t1q.wav"])
        self.assertEqual(load_bank(self.tmp).missing_for_interview(["t1"]), [])

    def test_unrecorded_phrase_blocks_interview(self):
        write_bank(self.tmp, [
            {"id": "open", "kind": "opening", "text": "привіт", "audio": "open.wav"},
            {"id": "close", "kind": "closing", "text": "дякую", "audio": "close.wav"},
            {"id": "p1", "kind": "probe", "text": "далі?", "audio": "p1.wav"},
            {"id": "t1q", "kind": "topic", "topic_id": "t1", "text": "про тему",
             "audio": "t1q.wav"},
            {"id": "later", "kind": "probe", "text": "ще не записана"},
        ], with_audio=["open.wav", "close.wav", "p1.wav", "t1q.wav"])
        gaps = load_bank(self.tmp).missing_for_interview(["t1"])
        self.assertTrue(any("later" in g for g in gaps))


class Scripted(LLMProvider):
    name = "scripted"
    supports_system_turns = True

    def __init__(self, script):
        self.script = list(script)
        self.systems = []

    def respond_json(self, system, messages, schema, max_tokens=2000):
        self.systems.append(system)
        if self.script:
            return self.script.pop(0)
        return {"phrase_id": "probe-what-next", "topic_id": "", "action": "probe",
                "coverage_note": ""}


def pick(phrase_id, action="probe"):
    return {"phrase_id": phrase_id, "topic_id": "", "action": action, "coverage_note": "ok"}


class TestSessionBankMode(unittest.TestCase):
    """Власна фікстура, а не `spaces/example`.

    Приклад свідомо лишається у вільному режимі й БЕЗ записів: фальшиві
    «записи» в шаблоні — та сама пастка, що велосипеди в новому просторі.
    Тому тут банк збирається в тимчасовій теці з підробленим аудіо.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = os.path.join(self.tmp, "example")
        shutil.copytree(EXAMPLE, self.dir)
        self.space, self.guide = load_space_dir(self.dir)

        phrases = json.loads(
            open(os.path.join(self.dir, "phrases.json"), encoding="utf-8").read())["phrases"]
        audio = []
        for phrase in phrases:
            phrase["audio"] = phrase["id"] + ".wav"
            audio.append(phrase["audio"])
        for topic in self.guide.topics:
            pid = "topic-%s" % topic.id
            phrases.append({"id": pid, "kind": "topic", "topic_id": topic.id,
                            "text": "Питання до теми %s." % topic.title,
                            "audio": pid + ".wav"})
            audio.append(pid + ".wav")
        write_bank(self.dir, phrases, with_audio=audio)
        self.bank = load_bank(self.dir)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _session(self, script):
        return Session(self.space, self.guide, Scripted(script), bank=self.bank)

    def test_repertoire_listed_in_system_prompt(self):
        session = self._session([pick("probe-what-next")])
        session.start()
        session.answer("щось")
        system = session.llm.systems[-1]
        self.assertIn("Доступні репліки", system)
        self.assertIn("probe-what-next", system)
        self.assertIn("ти їх ВИБИРАЄШ", system)

    def test_opening_comes_from_bank(self):
        session = self._session([])
        text = session.start()
        self.assertEqual(text, self.bank.opening.text)
        self.assertEqual(session.turns[0]["phrase_id"], self.bank.opening.id)
        self.assertTrue(session.turns[0]["audio"])

    def test_chosen_phrase_text_and_audio_returned(self):
        session = self._session([pick("probe-example")])
        session.start()
        turn = session.answer("відповідь")
        self.assertEqual(turn.phrase_id, "probe-example")
        self.assertEqual(turn.utterance, self.bank.by_id("probe-example").text)
        self.assertTrue(turn.audio)

    def test_unknown_phrase_id_rejected_then_fallback(self):
        bad = pick("такої-немає")
        session = self._session([bad, bad, bad])
        session.start()
        turn = session.answer("відповідь")
        self.assertTrue(turn.fallback_used)
        self.assertEqual(len(turn.guard_rejections), 3)
        self.assertIn(turn.phrase_id, [p.id for p in self.bank.probes])

    def test_model_cannot_speak_outside_the_bank(self):
        """Головна властивість режиму: сказати щось поза набором неможливо."""
        session = self._session([pick("такої-немає")] * 3)
        session.start()
        turn = session.answer("відповідь")
        texts = [p.text for p in self.bank.phrases]
        self.assertIn(turn.utterance, texts)

    def test_opening_cannot_be_reused_mid_interview(self):
        session = self._session([pick(self.bank.opening.id), pick("probe-what-next")])
        session.start()
        turn = session.answer("відповідь")
        self.assertNotEqual(turn.phrase_id, self.bank.opening.id)

    def test_immediate_repeat_rejected(self):
        session = self._session([pick("probe-example"), pick("probe-example"),
                                 pick("probe-what-next")])
        session.start()
        first = session.answer("раз")
        second = session.answer("два")
        self.assertEqual(first.phrase_id, "probe-example")
        self.assertNotEqual(second.phrase_id, "probe-example")

    def test_wrap_up_uses_recorded_closing(self):
        self.guide.max_turns = 2
        session = self._session([pick("probe-example"), pick("probe-what-next")])
        session.start()
        turn = session.answer("раз")
        while not session.done:
            turn = session.answer("ще")
        self.assertEqual(turn.phrase_id, self.bank.closing.id)
        self.assertTrue(turn.audio)

    def test_transcript_records_repertoire_mode(self):
        session = self._session([pick("probe-example")])
        session.start()
        session.answer("відповідь")
        self.assertEqual(session.to_dict()["repertoire"], "bank")

    def test_probe_limits_still_enforced_by_code(self):
        """Банк не скасовує жорстких правил: ліміти форсує ядро, як і раніше."""
        first = self.guide.topics[0]
        session = self._session([pick("probe-example"), pick("probe-what-next")] * 6)
        session.start()
        overrides = []
        for _ in range(first.max_probes + 1):
            turn = session.answer("щось")
            if turn.override:
                overrides.append(turn.override)
        self.assertTrue(any("ліміт уточнень" in o for o in overrides))


if __name__ == "__main__":
    unittest.main()
