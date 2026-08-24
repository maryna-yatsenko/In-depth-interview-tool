"""Заміна провайдера озвучення наживо і кеш ESPnet.

Перемикати провайдера перезапуском сервера не можна: це рве незавершені
інтервʼю респондентів. Тому провайдер живе в тримачі й підмінюється.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.server import TtsHolder, serve
from app.config.space import load_space_dir
from app.providers.base import ProviderError, TTSProvider
from app.providers.tts_espnet import EspnetTTS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Stoppable(TTSProvider):
    name = "stoppable"
    media_type = "audio/wav"

    def __init__(self):
        self.stopped = False

    def synthesize(self, text, voice=None):
        return b"RIFF"

    def stop(self):
        self.stopped = True


class TestTtsHolder(unittest.TestCase):
    def test_swap_replaces_provider(self):
        first, second = Stoppable(), Stoppable()
        holder = TtsHolder(first)
        holder.swap(second)
        self.assertIs(holder.current, second)

    def test_swap_stops_old_provider(self):
        """Старий провайдер тримає модель у памʼяті — його треба зупинити."""
        first, second = Stoppable(), Stoppable()
        holder = TtsHolder(first)
        holder.swap(second)
        self.assertTrue(first.stopped)
        self.assertFalse(second.stopped)

    def test_swap_to_none_allowed(self):
        first = Stoppable()
        holder = TtsHolder(first)
        holder.swap(None)
        self.assertIsNone(holder.current)
        self.assertTrue(first.stopped)

    def test_swap_to_same_does_not_stop_it(self):
        provider = Stoppable()
        holder = TtsHolder(provider)
        holder.swap(provider)
        self.assertFalse(provider.stopped)


def post(base, path, payload):
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class TestReloadEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()
        shutil.copytree(os.path.join(ROOT, "spaces", "example"),
                        os.path.join(cls.root, "example"))
        cls.space, cls.guide = load_space_dir(os.path.join(cls.root, "example"))
        # Явно закріплюємо режим: ці тести про вільний репертуар.
        cls.space.repertoire = "free"
        cls.httpd = serve(cls.space, cls.guide, {"provider": "mock"}, port=0,
                          admin_root=cls.root, tts=Stoppable())
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.root, ignore_errors=True)

    def _write_provider(self, provider):
        path = os.path.join(self.root, "example", "space.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["providers"]["tts"]["provider"] = provider
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)

    def test_reload_switches_to_browser(self):
        self._write_provider("browser")
        status, body = post(self.base, "/api/admin/tts/reload", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["provider"], "browser")
        self.assertEqual(body["voices"], [])

    def test_reload_reports_unknown_provider(self):
        self._write_provider("вигадка")
        status, body = post(self.base, "/api/admin/tts/reload", {})
        self.assertEqual(status, 400)
        self.assertIn("Доступні", body["error"])


class TestReloadWithoutAdmin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.space, cls.guide = load_space_dir(os.path.join(ROOT, "spaces", "example"))
        # Явно закріплюємо режим: ці тести про вільний репертуар.
        cls.space.repertoire = "free"
        cls.httpd = serve(cls.space, cls.guide, {"provider": "mock"}, port=0,
                          admin_root=None, tts=Stoppable())
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_reload_absent_when_admin_disabled(self):
        status, _ = post(self.base, "/api/admin/tts/reload", {})
        self.assertEqual(status, 404)


class TestEspnetCache(unittest.TestCase):
    """Кеш — те, що робить ESPnet придатним: 12 с синтезу проти 0,001 с із кешу.
    Перевіряємо без завантаження моделі: підкладаємо файл у кеш."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.model = os.path.join(self.tmp, "model")
        os.makedirs(self.model)
        self.audio = os.path.join(self.tmp, "audio")
        # Реальні шляхи потрібні лише для перевірки існування у конструкторі.
        self.python = sys.executable
        self.worker = os.path.join(ROOT, "bin", "espnet_worker.py")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _provider(self, voice="tetiana"):
        return EspnetTTS(python_path=self.python, worker_path=self.worker,
                         cache_folder=self.model, audio_cache=self.audio, voice=voice)

    def test_cached_audio_returned_without_worker(self):
        tts = self._provider()
        clean_text = "що ви зробили далі?"
        path = tts._cache_path(clean_text, "tetiana")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"RIFFcached")
        # Воркер не запускається: якби запустився, тест висів би на завантаженні.
        self.assertEqual(tts.synthesize("Що ви зробили далі?"), b"RIFFcached")

    def test_cache_key_depends_on_voice(self):
        tts = self._provider()
        self.assertNotEqual(tts._cache_path("текст", "tetiana"),
                            tts._cache_path("текст", "dmytro"))

    def test_cache_key_stable_for_same_input(self):
        tts = self._provider()
        self.assertEqual(tts._cache_path("текст", "lada"), tts._cache_path("текст", "lada"))

    def test_unknown_voice_rejected(self):
        with self.assertRaises(ProviderError) as ctx:
            self._provider(voice="Оксана")
        self.assertIn("oleksa", str(ctx.exception))

    def test_five_voices_with_gender(self):
        voices = self._provider().voices()
        self.assertEqual(len(voices), 5)
        males = [v["name"] for v in voices if v["gender"] == "Male"]
        self.assertEqual(sorted(males), ["dmytro", "mykyta", "oleksa"])

    def test_missing_model_folder_rejected(self):
        with self.assertRaises(ProviderError):
            EspnetTTS(python_path=self.python, worker_path=self.worker,
                      cache_folder=os.path.join(self.tmp, "немає"), audio_cache=self.audio)

    def test_empty_text_needs_no_worker(self):
        self.assertEqual(self._provider().synthesize("   "), b"")


if __name__ == "__main__":
    unittest.main()
