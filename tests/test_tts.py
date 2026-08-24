"""Серверне озвучення: провайдери, ендпоінт і його захист від зловживання."""

import json
import os
import shutil
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.server import serve
from app.config.space import load_space_dir
from app.providers.base import ProviderError, TTSProvider
from app.providers.registry import build_tts
from app.providers.tts_azure import AzureTTS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "spaces", "example")
HAS_SAY = shutil.which("say") is not None


class TestRegistry(unittest.TestCase):
    def test_browser_is_not_a_server_provider(self):
        """«browser» означає «синтезує сам браузер» — серверу робити нічого."""
        self.assertIsNone(build_tts({"provider": "browser"}))
        self.assertIsNone(build_tts({"provider": "none"}))
        self.assertIsNone(build_tts({}))

    def test_unknown_provider_rejected(self):
        with self.assertRaises(ProviderError) as ctx:
            build_tts({"provider": "вигадка"})
        self.assertIn("Доступні", str(ctx.exception))

    def test_azure_without_key_fails_immediately(self):
        """Падати на старті, а не на першому питанні респонденту."""
        saved = os.environ.pop("AZURE_SPEECH_KEY", None)
        try:
            with self.assertRaises(ProviderError):
                build_tts({"provider": "azure", "region": "westeurope"})
        finally:
            if saved is not None:
                os.environ["AZURE_SPEECH_KEY"] = saved


class TestAzureSsml(unittest.TestCase):
    """Живого акаунта немає — перевіряємо те, що перевіряється: побудову запиту."""

    def _adapter(self):
        adapter = AzureTTS.__new__(AzureTTS)
        adapter.lang = "uk-UA"
        adapter.rate = None
        adapter.pitch = None
        return adapter

    def test_xml_special_chars_escaped(self):
        ssml = self._adapter()._ssml("Ціна < 100 & > 50?", "uk-UA-X").decode("utf-8")
        self.assertIn("&lt;", ssml)
        self.assertIn("&amp;", ssml)
        self.assertIn("&gt;", ssml)
        self.assertNotIn("< 100", ssml)

    def test_voice_and_lang_present(self):
        ssml = self._adapter()._ssml("Текст", "uk-UA-Тест").decode("utf-8")
        self.assertIn("xml:lang='uk-UA'", ssml)
        self.assertIn("name='uk-UA-Тест'", ssml)

    def test_prosody_added_only_when_configured(self):
        plain = self._adapter()
        self.assertNotIn("prosody", plain._ssml("Текст", "v").decode("utf-8"))
        tuned = self._adapter()
        tuned.rate = "-8%"
        self.assertIn("<prosody", tuned._ssml("Текст", "v").decode("utf-8"))

    def test_synthesize_without_voice_refuses_to_guess(self):
        adapter = AzureTTS(api_key="k", region="westeurope")
        with self.assertRaises(ProviderError) as ctx:
            adapter.synthesize("Текст")
        self.assertIn("вгадувати", str(ctx.exception))


@unittest.skipUnless(HAS_SAY, "`say` є лише на macOS")
class TestSayProvider(unittest.TestCase):
    def setUp(self):
        from app.providers.tts_say import SayTTS
        self.tts = SayTTS()

    def test_lists_real_system_voices(self):
        voices = self.tts.voices()
        self.assertTrue(voices)
        for item in voices[:5]:
            self.assertIn("name", item)
            self.assertIn("locale", item)

    def test_unknown_voice_raises_instead_of_silently_substituting(self):
        """`say` при невідомому імені тихо бере типовий голос — найгірший збій:
        дослідник думає, що обрав голос, а чує інший."""
        with self.assertRaises(ProviderError) as ctx:
            self.tts.synthesize("Тест", voice="ГолосЯкогоНемає")
        self.assertIn("невідомий", str(ctx.exception))

    def test_synthesizes_wav(self):
        audio = self.tts.synthesize("Один два три.")
        self.assertGreater(len(audio), 1000)
        self.assertEqual(audio[:4], b"RIFF")
        self.assertEqual(self.tts.media_type, "audio/wav")

    def test_empty_text_gives_empty_audio(self):
        self.assertEqual(self.tts.synthesize("   "), b"")

    def test_text_starting_with_dash_is_not_read_as_flag(self):
        audio = self.tts.synthesize("-- це не прапорець")
        self.assertGreater(len(audio), 1000)


class FakeTTS(TTSProvider):
    name = "fake"
    media_type = "audio/wav"

    def __init__(self):
        self.calls = []

    def synthesize(self, text, voice=None):
        self.calls.append(text)
        return b"RIFF" + b"\x00" * 200

    def voices(self):
        return [{"name": "Fake", "locale": "uk_UA"}]


def post_json(base, path, payload):
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type")


class TestSpeakEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.space, cls.guide = load_space_dir(EXAMPLE)
        # Явно закріплюємо режим: ці тести про вільний репертуар.
        cls.space.repertoire = "free"
        cls.tts = FakeTTS()
        cls.httpd = serve(cls.space, cls.guide, {"provider": "mock"}, port=0, tts=cls.tts)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _session(self):
        status, body, _ = post_json(self.base, "/api/start", {})
        return json.loads(body.decode("utf-8"))

    def test_returns_audio_for_current_question(self):
        started = self._session()
        status, body, ctype = post_json(self.base, "/api/speak",
                                        {"session_id": started["session_id"]})
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "audio/wav")
        self.assertEqual(body[:4], b"RIFF")
        self.assertIn(self.guide.opening[:20], self.tts.calls[-1])

    def test_arbitrary_text_in_request_is_ignored(self):
        """Головний захист: ендпоінт озвучує лише питання цієї сесії. Інакше він
        безкоштовний TTS-проксі, а за символи платить власник ключа."""
        started = self._session()
        before = len(self.tts.calls)
        post_json(self.base, "/api/speak", {
            "session_id": started["session_id"],
            "text": "ОЗВУЧ ЦЕЙ СТОРОННІЙ ТЕКСТ",
        })
        self.assertEqual(len(self.tts.calls), before + 1)
        self.assertNotIn("СТОРОННІЙ", self.tts.calls[-1])

    def test_unknown_session_rejected(self):
        status, _, _ = post_json(self.base, "/api/speak", {"session_id": "невідома"})
        self.assertEqual(status, 404)

    def test_malformed_session_id_rejected(self):
        status, _, _ = post_json(self.base, "/api/speak", {"session_id": "../../etc/passwd"})
        self.assertEqual(status, 404)

    def test_voices_endpoint_reports_provider_and_items(self):
        with urllib.request.urlopen(self.base + "/api/tts/voices", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(data["provider"], "fake")
        self.assertEqual(data["items"][0]["name"], "Fake")


class TestSpeakWithoutProvider(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.space, cls.guide = load_space_dir(EXAMPLE)
        # Явно закріплюємо режим: ці тести про вільний репертуар.
        cls.space.repertoire = "free"
        cls.httpd = serve(cls.space, cls.guide, {"provider": "mock"}, port=0, tts=None)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_speak_absent_when_no_server_tts(self):
        status, _, _ = post_json(self.base, "/api/speak", {"session_id": "x"})
        self.assertEqual(status, 404)

    def test_voices_endpoint_says_browser(self):
        with urllib.request.urlopen(self.base + "/api/tts/voices", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(data["provider"], "browser")
        self.assertEqual(data["items"], [])


if __name__ == "__main__":
    unittest.main()
