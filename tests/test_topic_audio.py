"""Записаний голос дослідника: питання респондент чує живим голосом, а не
синтезом — перевіряємо саме HTTP-шлях (завантаження запису → видача через
/api/resume і /audio/topic/...), а не саме сховище (те вже покрито в
test_admin.py)."""

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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAVEL = os.path.join(ROOT, "spaces", "travel")


def post_json(base, path, payload):
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type")


def post_binary(base, path, content_type, data):
    req = urllib.request.Request(
        base + path, data=data, headers={"Content-Type": content_type}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def get_raw(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=5) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type")


class TestTopicAudioPlayback(unittest.TestCase):
    """Записаний голос дослідника — єдиний спосіб озвучити питання: нема
    запису — нема й audio_url, ніякого синтезу нема куди відкотитись.
    Працює на копії spaces/travel: пише справжній файл, тому не можна
    чіпати репозиторій напряму."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()
        shutil.copytree(TRAVEL, os.path.join(cls.root, "travel"))
        cls.space, cls.guide = load_space_dir(os.path.join(cls.root, "travel"))
        cls.httpd = serve(cls.space, cls.guide, {"provider": "mock"}, port=0,
                          admin_root=cls.root)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.root, ignore_errors=True)

    def tearDown(self):
        # cls.root — спільний на весь клас (окремий сервер на тест був би
        # значно повільнішим): запис, залишений одним тестом, інакше
        # підмінив би "нема запису" в наступному.
        from app.api import admin as admin_api
        admin_api.delete_topic_audio(self.root, "travel", "group-trips", "idea")

    def _json(self, path, payload):
        status, body, _ = post_json(self.base, path, payload)
        self.assertLess(status, 400, body)
        return json.loads(body.decode("utf-8"))

    def _reach_first_topic_level1(self):
        """opening → narrative → idea/1 (topic_id="idea") — гайд "подорожі"
        має фазу вільної розповіді між відкриттям і темами навіть у
        сценарному режимі: це той самий плаский Plan.script()."""
        started = self._json("/api/start", {"respondent_name": "Тестова Особа"})
        sid = started["session_id"]
        self._json("/api/answer", {"session_id": sid, "text": "Відповідь на відкриття."})
        self._json("/api/step", {"session_id": sid, "delta": 1})
        self._json("/api/answer", {"session_id": sid, "text": "Коротка розповідь про поїздку."})
        data = self._json("/api/step", {"session_id": sid, "delta": 1})
        self.assertEqual(data.get("source"), "idea/1", "тестовий хелпер розійшовся зі скриптом гайда")
        return sid

    def test_no_recording_means_no_audio_url(self):
        sid = self._reach_first_topic_level1()
        resumed = self._json("/api/resume", {"session_id": sid})
        self.assertIsNone(resumed["audio_url"])

    def test_recorded_question_is_served_via_audio_url(self):
        sid = self._reach_first_topic_level1()
        status, body = post_binary(
            self.base, "/api/admin/topic-audio?space=travel&guide=group-trips&topic=idea",
            "audio/webm", b"RECORDED-BY-RESEARCHER")
        self.assertEqual(status, 200, body)

        resumed = self._json("/api/resume", {"session_id": sid})
        self.assertEqual(resumed["audio_url"], "/audio/topic/travel/group-trips/idea")

        get_status, get_body, ctype = get_raw(self.base, resumed["audio_url"])
        self.assertEqual(get_status, 200)
        self.assertEqual(get_body, b"RECORDED-BY-RESEARCHER")
        self.assertEqual(ctype, "audio/webm")

    def test_level_two_question_ignores_level_one_recording(self):
        """«Уточнення» (рівень 2) — інше питання тієї самої теми: запис,
        зроблений для рівня 1, не має підмінити і його теж."""
        sid = self._reach_first_topic_level1()
        post_binary(self.base, "/api/admin/topic-audio?space=travel&guide=group-trips&topic=idea",
                   "audio/webm", b"LEVEL-1-RECORDING")
        self._json("/api/answer", {"session_id": sid, "text": "Хтось із друзів запропонував."})
        self._json("/api/step", {"session_id": sid, "delta": 1})
        resumed = self._json("/api/resume", {"session_id": sid})
        self.assertIsNone(resumed["audio_url"])


if __name__ == "__main__":
    unittest.main()
