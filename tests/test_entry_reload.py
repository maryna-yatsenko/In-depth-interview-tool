"""Збережене в панелі діє на респондента одразу: сервер перечитує конфіг простору,
а не тримає статус «чернетка» (чи старі питання) до перезапуску."""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api import server as server_module
from app.api.server import SessionStore, make_handler
from app.config.space import load_space_dir

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestEntryReload(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        for key in ("example", "other"):
            shutil.copytree(os.path.join(ROOT, "spaces", "example"), os.path.join(self.root, key))
        self.space_path = os.path.join(self.root, "other", "space.json")
        self._set(draft=True)
        self.old_ttl = server_module.ENTRY_RECHECK_SECONDS
        server_module.ENTRY_RECHECK_SECONDS = 0.0
        space, guide = load_space_dir(os.path.join(self.root, "example"))
        llm = {"provider": "mock"}
        handler = make_handler(space, guide, llm, SessionStore(space, guide, llm, None), self.root)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        server_module.ENTRY_RECHECK_SECONDS = self.old_ttl
        shutil.rmtree(self.root, ignore_errors=True)

    def _set(self, **fields):
        with open(self.space_path, encoding="utf-8") as fh:
            data = json.load(fh)
        data.update(fields)
        with open(self.space_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        # Різний mtime навіть на швидких файлових системах.
        stat = os.stat(self.space_path)
        os.utime(self.space_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000))

    def _start_status(self):
        request = urllib.request.Request(
            "http://127.0.0.1:%d/api/start?space=other" % self.port, method="POST",
            data=json.dumps({"respondent_name": "Тест", "record_voice": False}).encode(),
            headers={"Content-Type": "application/json"})
        try:
            return urllib.request.urlopen(request).status, ""
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    def test_publishing_in_panel_takes_effect_without_restart(self):
        status, body = self._start_status()
        self.assertEqual(status, 409)
        self.assertIn("чернетка", body)
        self._set(draft=False)
        time.sleep(0.01)
        status, body = self._start_status()
        self.assertNotEqual(status, 409, body)


if __name__ == "__main__":
    unittest.main()
