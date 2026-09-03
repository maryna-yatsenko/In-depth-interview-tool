"""Piper: локальна нейронна модель. Тести запускати венвівським інтерпретатором:

    .venv/bin/python -m unittest discover -s tests

Системний python3 пакета не має, і ці тести просто пропустяться — це нормально,
але тоді вони нічого не перевіряють.
"""

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.server import PREVIEW_TEXT, serve
from app.config.space import load_space_dir
from app.providers.base import ProviderError
from app.providers.tts_piper import PiperTTS

try:
    import piper as _piper_pkg
except ImportError:
    _piper_pkg = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "spaces", "example")
MODEL = os.path.join(ROOT, "voices", "piper", "uk_UA-ukrainian_tts-medium.onnx")
READY = _piper_pkg is not None and os.path.isfile(MODEL)


@unittest.skipUnless(READY, "потрібен пакет piper і модель у voices/piper/")
class TestPiper(unittest.TestCase):
    def test_lists_three_ukrainian_voices(self):
        voices = PiperTTS(model_path=MODEL).voices()
        names = sorted(v["name"] for v in voices)
        self.assertEqual(names, ["lada", "mykyta", "tetiana"])
        for item in voices:
            self.assertEqual(item["locale"], "uk_UA")

    def test_unknown_voice_rejected_with_list(self):
        with self.assertRaises(ProviderError) as ctx:
            PiperTTS(model_path=MODEL, voice="Оксана")
        message = str(ctx.exception)
        self.assertIn("mykyta", message)

    def test_missing_model_file_rejected(self):
        with self.assertRaises(ProviderError):
            PiperTTS(model_path=os.path.join(ROOT, "voices", "piper", "немає.onnx"))

    def test_synthesizes_wav_for_each_voice(self):
        for name in ("lada", "mykyta", "tetiana"):
            audio = PiperTTS(model_path=MODEL, voice=name).synthesize("Один два три.")
            self.assertEqual(audio[:4], b"RIFF", name)
            self.assertGreater(len(audio), 5000, name)

    def test_different_voices_give_different_audio(self):
        text = "Розкажіть про останній випадок."
        a = PiperTTS(model_path=MODEL, voice="mykyta").synthesize(text)
        b = PiperTTS(model_path=MODEL, voice="tetiana").synthesize(text)
        self.assertNotEqual(a, b, "вибір голосу не застосувався")

    def test_parameters_reach_synthesis_config(self):
        """Через нестабільність моделі (розкид тривалості до 0,94 с) перевіряти
        передачу параметрів по довжині аудіо неможливо — перевіряємо виклик."""
        piper = PiperTTS(model_path=MODEL, voice="mykyta", length_scale=1.1,
                         sentence_silence=0.4, noise_scale=0.35, noise_w_scale=0.4)
        seen = {}
        original = piper._voice.synthesize

        def spy(text, syn_config=None, **kwargs):
            seen["config"] = syn_config
            return original(text, syn_config=syn_config, **kwargs)

        piper._voice.synthesize = spy
        try:
            piper.synthesize("Один два три.")
        finally:
            piper._voice.synthesize = original
        config = seen["config"]
        self.assertEqual(config.speaker_id, 1)
        self.assertEqual(config.length_scale, 1.1)
        self.assertEqual(config.noise_scale, 0.35)
        self.assertEqual(config.noise_w_scale, 0.4)

    def test_optional_parameters_omitted_when_unset(self):
        piper = PiperTTS(model_path=MODEL)
        seen = {}
        original = piper._voice.synthesize

        def spy(text, syn_config=None, **kwargs):
            seen["config"] = syn_config
            return original(text, syn_config=syn_config, **kwargs)

        piper._voice.synthesize = spy
        try:
            piper.synthesize("Один два три.")
        finally:
            piper._voice.synthesize = original
        config = seen["config"]
        self.assertIsNone(config.speaker_id)
        self.assertIsNone(config.length_scale)
        self.assertIsNone(config.noise_scale)
        self.assertIsNone(config.noise_w_scale)

    def test_zero_noise_makes_output_reproducible(self):
        """Нульовий шум = однакове аудіо для всіх респондентів. Це методологічна
        властивість, тому вона під тестом."""
        text = "Розкажіть про останній випадок."
        piper = PiperTTS(model_path=MODEL, voice="tetiana",
                         noise_scale=0.0, noise_w_scale=0.0)
        first = piper.synthesize(text)
        second = piper.synthesize(text)
        self.assertEqual(first, second)

    def test_empty_text_gives_empty_audio(self):
        self.assertEqual(PiperTTS(model_path=MODEL).synthesize("  "), b"")


def post(base, path, payload):
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type")


class RecordingTTS:
    name = "recording"
    media_type = "audio/wav"

    def __init__(self):
        self.calls = []

    def synthesize(self, text, voice=None):
        self.calls.append((text, voice))
        return b"RIFF" + b"\x00" * 100

    def voices(self):
        return [{"name": "a", "locale": "uk_UA"}, {"name": "b", "locale": "uk_UA"}]


class TestAdminPreview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.space, cls.guide = load_space_dir(EXAMPLE)
        # Явно закріплюємо режим: ці тести про вільний репертуар.
        cls.space.repertoire = "free"
        cls.tts = RecordingTTS()
        cls.httpd = serve(cls.space, cls.guide, {"provider": "mock"}, port=0,
                          admin_root=os.path.join(ROOT, "spaces"), tts=cls.tts)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_preview_uses_fixed_text_and_chosen_voice(self):
        status, body, ctype = post(self.base, "/api/admin/tts/preview", {"voice": "b"})
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "audio/wav")
        self.assertEqual(self.tts.calls[-1], (PREVIEW_TEXT, "b"))

    def test_preview_ignores_supplied_text(self):
        """Голос обирається, текст — ні: інакше це безкоштовний синтез чого
        завгодно, тільки за адресою адмінки."""
        post(self.base, "/api/admin/tts/preview",
             {"voice": "a", "text": "ОЗВУЧ ЦЕ СТОРОННЄ"})
        said, _ = self.tts.calls[-1]
        self.assertEqual(said, PREVIEW_TEXT)
        self.assertNotIn("СТОРОННЄ", said)


class TestPreviewWithoutAdmin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.space, cls.guide = load_space_dir(EXAMPLE)
        # Явно закріплюємо режим: ці тести про вільний репертуар.
        cls.space.repertoire = "free"
        cls.httpd = serve(cls.space, cls.guide, {"provider": "mock"}, port=0,
                          admin_root=None, tts=RecordingTTS())
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_preview_absent_when_admin_disabled(self):
        status, _, _ = post(self.base, "/api/admin/tts/preview", {"voice": "a"})
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()


class TestPreviewTuning(unittest.TestCase):
    """Превʼю мусить звучати так, як накрутив дослідник, і НЕ змінювати конфіг
    живого інтервʼю, яке може йти в іншій вкладці."""

    @classmethod
    def setUpClass(cls):
        cls.space, cls.guide = load_space_dir(EXAMPLE)
        # Явно закріплюємо режим: ці тести про вільний репертуар.
        cls.space.repertoire = "free"
        cls.tts = RecordingTTS()
        cls.tts.length_scale = 1.06
        cls.tts.sentence_silence = 0.4
        cls.tts.add_stress = True
        cls.httpd = serve(cls.space, cls.guide, {"provider": "mock"}, port=0,
                          admin_root=os.path.join(ROOT, "spaces"), tts=cls.tts)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_tuning_applied_during_preview(self):
        seen = {}
        original = self.tts.synthesize

        def spy(text, voice=None):
            seen["length_scale"] = self.tts.length_scale
            seen["add_stress"] = self.tts.add_stress
            return original(text, voice)

        self.tts.synthesize = spy
        try:
            post(self.base, "/api/admin/tts/preview",
                 {"voice": "b", "length_scale": 1.3, "add_stress": False})
        finally:
            self.tts.synthesize = original
        self.assertEqual(seen["length_scale"], 1.3)
        self.assertFalse(seen["add_stress"])

    def test_settings_restored_after_preview(self):
        post(self.base, "/api/admin/tts/preview",
             {"voice": "b", "length_scale": 1.3, "add_stress": False})
        self.assertEqual(self.tts.length_scale, 1.06)
        self.assertEqual(self.tts.sentence_silence, 0.4)
        self.assertTrue(self.tts.add_stress)

    def test_preview_text_still_fixed_with_tuning(self):
        post(self.base, "/api/admin/tts/preview",
             {"voice": "b", "length_scale": 1.3, "text": "СТОРОННІЙ ТЕКСТ"})
        self.assertEqual(self.tts.calls[-1][0], PREVIEW_TEXT)
