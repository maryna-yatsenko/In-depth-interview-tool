"""HTTP-шар: перевіряємо контракт, а не верстку.

Веб-клієнт перевіряється в браузері (це зробили вручну); тут — те, що клієнт
може зламати непомітно: коди помилок, відсутність ключів у видачі, і що
транскрипт таки зберігається.
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

from app.api.server import serve
from app.config.space import load_space_dir
from app.storage import local as store_files

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "spaces", "example")


def post(base, path, payload):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


class TestOneModelPerProcess(unittest.TestCase):
    """Модель будується ОДИН раз на процес, а не на кожну сесію.

    Раніше `build_llm` викликався на кожен старт і кожне відновлення. Для
    локальної моделі це ще 3,2 ГБ у памʼяті на сесію: кілька сесій, і процес
    убивала система — сторінка отримувала «Failed to fetch» посеред інтервʼю.
    Спостережено двічі за один день, тому тест є.
    """

    def setUp(self):
        from app.api import server as server_module
        self.module = server_module
        self.space, self.guide = load_space_dir(EXAMPLE)
        self.built = []

        def counting_factory(cfg):
            from app.providers.llm_mock import MockLLM
            llm = MockLLM()
            self.built.append(llm)
            return llm

        self._orig = server_module.build_llm
        server_module.build_llm = counting_factory
        self._dirs = (store_files.DEFAULT_DIR, store_files.LIVE_DIR)
        self._root = tempfile.mkdtemp()
        store_files.DEFAULT_DIR = os.path.join(self._root, "sessions")
        store_files.LIVE_DIR = os.path.join(self._root, "live")

    def tearDown(self):
        self.module.build_llm = self._orig
        store_files.DEFAULT_DIR, store_files.LIVE_DIR = self._dirs
        shutil.rmtree(self._root, ignore_errors=True)

    def test_many_sessions_share_one_model(self):
        store = self.module.SessionStore(self.space, self.guide, {"provider": "mock"})
        first = store.new()
        second = store.new()
        first.start()
        store.persist(first)
        # Відновлення теж не має будувати нову модель.
        store._items.clear()
        resumed = store.get(first.session_id)

        self.assertEqual(len(self.built), 1,
                         "модель збудована %d разів замість одного" % len(self.built))
        self.assertIs(first.llm, second.llm)
        self.assertIs(resumed.llm, first.llm)


class TestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.space, cls.guide = load_space_dir(EXAMPLE)
        # Явно закріплюємо режим: ці тести про вільний репертуар.
        cls.space.repertoire = "free"
        # Транскрипти тестів не мають сипатись у робочу теку дослідника.
        cls._orig_dirs = (store_files.DEFAULT_DIR, store_files.LIVE_DIR)
        cls._root = tempfile.mkdtemp()
        store_files.DEFAULT_DIR = os.path.join(cls._root, "sessions")
        store_files.LIVE_DIR = os.path.join(cls._root, "live")
        cls.httpd = serve(cls.space, cls.guide, {"provider": "mock"}, port=0)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.tmp = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        store_files.DEFAULT_DIR = cls._orig_dirs[0]
        store_files.LIVE_DIR = cls._orig_dirs[1]
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)
        shutil.rmtree(cls._root, ignore_errors=True)

    def test_space_payload_has_no_secrets(self):
        status, data = get(self.base, "/api/space")
        self.assertEqual(status, 200)
        blob = json.dumps(data).lower()
        for forbidden in ("api_key", "apikey", "sk-ant", "token", "secret"):
            self.assertNotIn(forbidden, blob, "у видачу клієнту протекло: %s" % forbidden)
        self.assertEqual(data["voice"]["stt"], "browser")
        self.assertEqual(data["topics_total"], len(self.guide.topics))

    def test_space_payload_carries_interface_and_voice_settings(self):
        status, data = get(self.base, "/api/space")
        self.assertEqual(status, 200)
        self.assertIn(data["interface"]["mode"], ("voice", "text"))
        # Клієнту потрібні лише параметри звучання.
        for key in data.get("tts", {}):
            self.assertIn(key, ("voice", "rate", "pitch", "gap"))

    def test_provider_credentials_never_reach_client(self):
        """Якщо в конфіг простору колись покладуть ключ провайдера — він не має
        поїхати в браузер разом із налаштуваннями голосу."""
        original = self.space.providers.get("tts")
        self.space.providers["tts"] = {
            "provider": "browser", "voice": "Леся", "rate": 1.0,
            "api_key": "sk-НЕ-МАЄ-ВИТЕКТИ", "region": "eu-west",
        }
        try:
            _, data = get(self.base, "/api/space")
            blob = json.dumps(data, ensure_ascii=False)
            self.assertNotIn("НЕ-МАЄ-ВИТЕКТИ", blob)
            self.assertNotIn("api_key", blob)
            self.assertNotIn("region", blob)
            self.assertEqual(data["tts"]["voice"], "Леся")
        finally:
            if original is None:
                self.space.providers.pop("tts", None)
            else:
                self.space.providers["tts"] = original

    def test_payload_reports_autoplay(self):
        """Клієнт мусить знати, чи вмикати голос сам — і за замовчуванням ні."""
        _, data = get(self.base, "/api/space")
        self.assertIn("autoplay", data["interface"])
        self.assertIsInstance(data["interface"]["autoplay"], bool)

    def test_payload_reports_expected_words(self):
        """Клієнт мусить знати, який обсяг ми називаємо очікуваним."""
        _, data = get(self.base, "/api/space")
        self.assertIsInstance(data["interface"]["expected_words"], int)
        self.assertGreaterEqual(data["interface"]["expected_words"], 1)

    def test_start_returns_opening(self):
        status, data = post(self.base, "/api/start", {})
        self.assertEqual(status, 200)
        self.assertTrue(data["session_id"])
        self.assertIn(self.guide.opening[:20], data["utterance"])
        self.assertFalse(data["done"])

    def test_empty_answer_rejected(self):
        _, started = post(self.base, "/api/start", {})
        status, data = post(self.base, "/api/answer", {"session_id": started["session_id"], "text": "   "})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_unknown_session_rejected(self):
        status, data = post(self.base, "/api/answer", {"session_id": "неіснуюча", "text": "щось"})
        self.assertEqual(status, 404)

    def test_full_interview_completes_and_saves(self):
        _, started = post(self.base, "/api/start", {})
        sid = started["session_id"]
        done = False
        for _ in range(40):
            status, data = post(self.base, "/api/answer", {"session_id": sid, "text": "якась відповідь"})
            self.assertEqual(status, 200)
            if data["done"]:
                done = True
                self.assertIn("saved_to", data)
                self.assertTrue(os.path.exists(data["saved_to"]))
                saved = json.load(open(data["saved_to"], encoding="utf-8"))
                self.assertEqual(saved["prompt_version"], "interviewer.v1")
                self.assertTrue(saved["completed"])
                break
        self.assertTrue(done, "інтервʼю не завершилось за 40 реплік")

    def test_draft_returns_checklist_without_touching_transcript(self):
        """Жива перевірка не пише в транскрипт: це чернетка, не відповідь."""
        _, started = post(self.base, "/api/start", {})
        sid = started["session_id"]
        live = os.path.join(store_files.LIVE_DIR, "%s.json" % sid)
        before = json.load(open(live, encoding="utf-8"))["turns"]

        status, data = post(self.base, "/api/draft",
                           {"session_id": sid, "text": "Ми поїхали в Карпати."})
        self.assertEqual(status, 200)
        self.assertIn("checklist", data)
        self.assertIn("all_covered", data)
        after = json.load(open(live, encoding="utf-8"))["turns"]
        self.assertEqual(len(before), len(after))

    def test_draft_reset_accepted(self):
        _, started = post(self.base, "/api/start", {})
        sid = started["session_id"]
        status, data = post(self.base, "/api/draft", {"session_id": sid, "reset": True})
        self.assertEqual(status, 200)
        self.assertFalse(data["all_covered"])

    def test_draft_unknown_session_is_404(self):
        status, _ = post(self.base, "/api/draft", {"session_id": "нема", "text": "щось"})
        self.assertEqual(status, 404)

    def test_answer_payload_says_whether_everything_covered(self):
        """Клієнт вмикає «Надіслати» саме за цим полем."""
        _, started = post(self.base, "/api/start", {})
        sid = started["session_id"]
        _, data = post(self.base, "/api/answer",
                       {"session_id": sid, "text": "перша відповідь"})
        self.assertIn("all_covered", data)
        self.assertIsInstance(data["all_covered"], bool)

    def test_answering_finished_session_rejected(self):
        _, started = post(self.base, "/api/start", {})
        sid = started["session_id"]
        for _ in range(40):
            _, data = post(self.base, "/api/answer", {"session_id": sid, "text": "відповідь"})
            if data.get("done"):
                break
        # Сесія завершена й прибрана зі стора — далі 404, а не тихе продовження.
        status, _ = post(self.base, "/api/answer", {"session_id": sid, "text": "ще одна"})
        self.assertIn(status, (404, 409))

    def test_live_state_written_after_each_turn(self):
        _, started = post(self.base, "/api/start", {})
        sid = started["session_id"]
        live = os.path.join(store_files.LIVE_DIR, "%s.json" % sid)
        self.assertTrue(os.path.exists(live), "стан не збережено одразу після старту")
        post(self.base, "/api/answer", {"session_id": sid, "text": "перша відповідь"})
        saved = json.load(open(live, encoding="utf-8"))
        self.assertTrue(any(x["role"] == "respondent" for x in saved["turns"]))

    def test_resume_returns_last_question(self):
        _, started = post(self.base, "/api/start", {})
        sid = started["session_id"]
        _, answered = post(self.base, "/api/answer", {"session_id": sid, "text": "щось сказав"})
        status, resumed = post(self.base, "/api/resume", {"session_id": sid})
        self.assertEqual(status, 200)
        self.assertEqual(resumed["utterance"], answered["utterance"])
        self.assertEqual(resumed["answered"], 1)

    def test_resume_survives_server_restart(self):
        """Головне, що закриває TD-5: нова памʼять, той самий стан із диска."""
        _, started = post(self.base, "/api/start", {})
        sid = started["session_id"]
        post(self.base, "/api/answer", {"session_id": sid, "text": "відповідь до перезапуску"})

        fresh = serve(self.space, self.guide, {"provider": "mock"}, port=0)
        base2 = "http://127.0.0.1:%d" % fresh.server_address[1]
        thread = threading.Thread(target=fresh.serve_forever, daemon=True)
        thread.start()
        try:
            status, resumed = post(base2, "/api/resume", {"session_id": sid})
            self.assertEqual(status, 200, "сесія не відновилась у новому процесі")
            self.assertEqual(resumed["answered"], 1)
            status, nxt = post(base2, "/api/answer", {"session_id": sid, "text": "продовжую"})
            self.assertEqual(status, 200)
        finally:
            fresh.shutdown()
            fresh.server_close()

    def test_resume_unknown_session(self):
        status, _ = post(self.base, "/api/resume", {"session_id": "deadbeef"})
        self.assertEqual(status, 404)

    def test_resume_rejects_malformed_id(self):
        status, _ = post(self.base, "/api/resume", {"session_id": "../../etc/passwd"})
        self.assertEqual(status, 404)

    def test_finished_session_drops_live_state(self):
        _, started = post(self.base, "/api/start", {})
        sid = started["session_id"]
        for _ in range(40):
            _, data = post(self.base, "/api/answer", {"session_id": sid, "text": "відповідь"})
            if data.get("done"):
                break
        self.assertFalse(os.path.exists(os.path.join(store_files.LIVE_DIR, "%s.json" % sid)),
                         "живий стан не прибрано після завершення")
        self.assertTrue(os.path.exists(os.path.join(store_files.DEFAULT_DIR, "%s.json" % sid)))

    def test_sessions_listing(self):
        status, data = get(self.base, "/api/sessions")
        self.assertEqual(status, 200)
        self.assertIsInstance(data["items"], list)
        for item in data["items"]:
            self.assertNotIn("turns_text", item)
            self.assertIsInstance(item["turns"], int)

    def test_path_traversal_blocked(self):
        req = urllib.request.Request(self.base + "/../app/providers/llm_anthropic.py")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode("utf-8", "replace")
            self.assertNotIn("ANTHROPIC", body)
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 404)


if __name__ == "__main__":
    unittest.main()
