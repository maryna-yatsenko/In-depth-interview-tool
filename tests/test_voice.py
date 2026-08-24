"""Запис голосу респондента: сховище і правила доступу.

Головне, що тут перевіряється, — не «файл зберігся», а **дві умови, без яких
він зберігатись не має**: простір це дозволяє І людина погодилась. Голос
неможливо деідентифікувати: імʼя, вимовлене вголос, лишається в записі
назавжди, і сам голос теж є персональними даними. Тому запис потай — не баг, а
порушення згоди.
"""

import io
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
from app.storage import voice as voice_files

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "spaces", "example")

# Найкоротший валідний webm-подібний блоб: вміст нам не важливий, важливий
# шлях «прийшло → лягло на диск → віддалось назад».
CLIP = b"\x1a\x45\xdf\xa3" + b"0" * 64


def post_bytes(base, path, data, content_type="audio/webm"):
    req = urllib.request.Request(base + path, data=data, method="POST",
                                headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def post_json(base, path, payload):
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def get_raw(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class TestVoiceStorage(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_saves_and_reads_back(self):
        name = voice_files.save_clip("abc123", CLIP, "audio/webm", root=self.root)
        self.assertTrue(name.endswith(".webm"))
        self.assertEqual(voice_files.read_clip("abc123", name, root=self.root), CLIP)

    def test_numbering_is_stable(self):
        first = voice_files.save_clip("abc123", CLIP, "audio/webm", root=self.root)
        second = voice_files.save_clip("abc123", CLIP, "audio/webm", root=self.root)
        self.assertEqual([first, second], ["001.webm", "002.webm"])

    def test_codec_parameters_are_ignored(self):
        name = voice_files.save_clip("abc123", CLIP, "audio/webm;codecs=opus",
                                     root=self.root)
        self.assertTrue(name.endswith(".webm"))

    def test_unknown_type_rejected(self):
        with self.assertRaises(voice_files.VoiceError):
            voice_files.save_clip("abc123", CLIP, "application/zip", root=self.root)

    def test_oversized_clip_rejected(self):
        big = b"0" * (voice_files.MAX_CLIP_BYTES + 1)
        with self.assertRaises(voice_files.VoiceError) as ctx:
            voice_files.save_clip("abc123", big, "audio/webm", root=self.root)
        self.assertEqual(ctx.exception.status, 413)

    def test_path_traversal_rejected(self):
        """Імʼя файлу приходить з мережі, отже це вхідні дані, а не істина."""
        for bad in ("../../secret", "a/b", ".hidden"):
            with self.assertRaises(voice_files.VoiceError):
                voice_files.clip_path("abc123", bad, root=self.root)

    def test_delete_removes_from_disk(self):
        """«Сказати заново» мусить видаляти, а не позначати скасованим."""
        name = voice_files.save_clip("abc123", CLIP, "audio/webm", root=self.root)
        self.assertEqual(voice_files.delete_clips("abc123", [name], root=self.root), 1)
        self.assertEqual(voice_files.list_clips("abc123", root=self.root), [])

    def test_partial_upload_leaves_no_clip(self):
        voice_files.save_clip("abc123", CLIP, "audio/webm", root=self.root)
        directory = voice_files.session_dir("abc123", root=self.root)
        io.open(os.path.join(directory, "999.webm.part"), "wb").write(b"half")
        self.assertEqual(voice_files.list_clips("abc123", root=self.root), ["001.webm"])


class TestVoiceApiNeedsConsent(unittest.TestCase):
    """Простір із записом УВІМКНЕНИМ — вирішує згода респондента."""

    @classmethod
    def setUpClass(cls):
        cls.space, cls.guide = load_space_dir(EXAMPLE)
        cls.space.repertoire = "free"
        cls.space.interface["record_voice"] = True
        cls._orig = (store_files.DEFAULT_DIR, store_files.LIVE_DIR, voice_files.VOICE_DIR)
        cls._root = tempfile.mkdtemp()
        store_files.DEFAULT_DIR = os.path.join(cls._root, "sessions")
        store_files.LIVE_DIR = os.path.join(cls._root, "live")
        voice_files.VOICE_DIR = os.path.join(cls._root, "voice")
        cls.httpd = serve(cls.space, cls.guide, {"provider": "mock"}, port=0)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        store_files.DEFAULT_DIR, store_files.LIVE_DIR, voice_files.VOICE_DIR = cls._orig
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls._root, ignore_errors=True)

    def _start(self, consent):
        _, data = post_json(self.base, "/api/start", {"record_voice": consent})
        return data["session_id"], data

    def test_without_consent_upload_is_refused(self):
        sid, started = self._start(False)
        self.assertFalse(started["voice_consent"])
        status, body = post_bytes(
            self.base, "/api/voice?session_id=%s" % sid, CLIP)
        self.assertEqual(status, 403)
        self.assertIn("згоди", body["error"])

    def test_with_consent_clip_is_stored_and_served(self):
        sid, started = self._start(True)
        self.assertTrue(started["voice_consent"])
        status, body = post_bytes(
            self.base, "/api/voice?session_id=%s" % sid, CLIP)
        self.assertEqual(status, 200)
        self.assertEqual(body["pending"], [body["clip"]])

        status, raw = get_raw(self.base, body["url"])
        self.assertEqual(status, 200)
        self.assertEqual(raw, CLIP)

    def test_clip_is_attached_to_the_answer_it_belongs_to(self):
        sid, _ = self._start(True)
        post_bytes(self.base, "/api/voice?session_id=%s" % sid, CLIP)
        post_json(self.base, "/api/answer", {"session_id": sid, "text": "відповідь"})

        live = json.load(io.open(os.path.join(store_files.LIVE_DIR, "%s.json" % sid),
                                 encoding="utf-8"))
        spoken = [t for t in live["turns"] if t["role"] == "respondent"]
        self.assertEqual(spoken[-1].get("voice"), ["001.webm"])
        # Прикріплені записи більше не «в очікуванні»: наступна відповідь своя.
        self.assertEqual(live["state"].get("pending_voice"), [])
        self.assertTrue(live.get("voice_consent"))

    def test_pending_clips_come_back_in_payloads(self):
        """Записи мусять переживати перезавантаження сторінки.

        У памʼяті браузера blob-и зникають, а файли лишаються на диску. Без
        цього «Мій голос» після перезавантаження мертвий, хоч запис є.
        """
        sid, _ = self._start(True)
        _, body = post_bytes(self.base, "/api/voice?session_id=%s" % sid, CLIP)

        _, resumed = post_json(self.base, "/api/resume", {"session_id": sid})
        self.assertEqual(resumed["voice"], [body["clip"]])

        _, draft = post_json(self.base, "/api/draft",
                             {"session_id": sid, "text": "щось сказане"})
        self.assertEqual(draft["voice"], [body["clip"]])

    def test_saying_it_again_deletes_the_clip(self):
        sid, _ = self._start(True)
        _, body = post_bytes(self.base, "/api/voice?session_id=%s" % sid, CLIP)
        post_json(self.base, "/api/draft", {"session_id": sid, "reset": True})
        self.assertEqual(voice_files.list_clips(sid), [])
        status, _ = get_raw(self.base, body["url"])
        self.assertEqual(status, 404)

    def test_unknown_session_is_404(self):
        # Ідентифікатор ASCII навмисно: кириличний в URL urllib не закодує, і
        # тест упав би на власній помилці, а не на поведінці сервера.
        status, _ = post_bytes(self.base, "/api/voice?session_id=deadbeef00", CLIP)
        self.assertEqual(status, 404)


class TestFinishedSessionListsClips(unittest.TestCase):
    """Дослідник мусить бачити зі списку, яке інтервʼю можна переслухати."""

    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_list_sessions_collects_clip_names_from_turns(self):
        payload = {
            "session_id": "abc123", "space": "s", "guide": "g",
            "prompt_version": "interviewer.v1", "started_at": "2026-08-23T10:00:00",
            "completed": True, "voice_consent": True,
            "turns": [
                {"role": "interviewer", "text": "питання"},
                {"role": "respondent", "text": "відповідь", "voice": ["001.webm"]},
                {"role": "respondent", "text": "ще", "voice": ["002.webm", "003.webm"]},
                {"role": "respondent", "text": "без запису"},
            ],
        }
        store_files.save_session(payload, directory=self.root)
        items = store_files.list_sessions(directory=self.root)
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["voice_consent"])
        self.assertEqual(items[0]["voice"], ["001.webm", "002.webm", "003.webm"])

    def test_session_without_recordings_reports_empty(self):
        store_files.save_session({
            "session_id": "def456", "space": "s", "guide": "g",
            "started_at": "2026-08-23T11:00:00",
            "turns": [{"role": "respondent", "text": "текстом"}],
        }, directory=self.root)
        items = store_files.list_sessions(directory=self.root)
        self.assertEqual(items[0]["voice"], [])
        self.assertFalse(items[0]["voice_consent"])


class TestVoiceOffBySpace(unittest.TestCase):
    """Простір запису не просить — згода респондента нічого не змінює."""

    @classmethod
    def setUpClass(cls):
        cls.space, cls.guide = load_space_dir(EXAMPLE)
        cls.space.repertoire = "free"
        cls.space.interface.pop("record_voice", None)
        cls._orig = (store_files.DEFAULT_DIR, store_files.LIVE_DIR, voice_files.VOICE_DIR)
        cls._root = tempfile.mkdtemp()
        store_files.DEFAULT_DIR = os.path.join(cls._root, "sessions")
        store_files.LIVE_DIR = os.path.join(cls._root, "live")
        voice_files.VOICE_DIR = os.path.join(cls._root, "voice")
        cls.httpd = serve(cls.space, cls.guide, {"provider": "mock"}, port=0)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        store_files.DEFAULT_DIR, store_files.LIVE_DIR, voice_files.VOICE_DIR = cls._orig
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls._root, ignore_errors=True)

    def test_default_is_no_recording(self):
        _, space = post_json(self.base, "/api/start", {"record_voice": True})
        self.assertFalse(space["voice_consent"],
                         "простір запису не просив — згоди не може бути")
        status, body = post_bytes(
            self.base, "/api/voice?session_id=%s" % space["session_id"], CLIP)
        self.assertEqual(status, 403)
        self.assertIn("вимкнений", body["error"])

    def test_space_payload_says_recording_is_off(self):
        req = urllib.request.urlopen(self.base + "/api/space", timeout=5)
        data = json.loads(req.read().decode("utf-8"))
        self.assertFalse(data["interface"]["record_voice"])


if __name__ == "__main__":
    unittest.main()
