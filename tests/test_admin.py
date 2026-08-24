"""Адмінка: чи не пускає вона на диск те, що завалить наступне інтервʼю."""

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

from app.api import admin as admin_api
from app.api.server import serve
from app.config.space import load_guide, load_space, load_space_dir

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPACES = os.path.join(ROOT, "spaces")


class TestAdminFiles(unittest.TestCase):
    def setUp(self):
        # Працюємо на копії: тести не мають чіпати справжні простори дослідника.
        self.root = tempfile.mkdtemp()
        shutil.copytree(os.path.join(SPACES, "example"), os.path.join(self.root, "example"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    # ── створення ────────────────────────────────────────────────────────
    def test_new_space_is_draft_without_template_content(self):
        admin_api.create_space(self.root, "onboarding", "Онбординг")
        space = load_space(os.path.join(self.root, "onboarding", "space.json"))
        guide = load_guide(os.path.join(self.root, "onboarding", "guides", "first.json"))

        self.assertTrue(space.draft, "новий простір мусить бути чернеткою")
        self.assertEqual(space.title, "Онбординг")
        self.assertEqual(space.domain_vocabulary, [])
        # Головне: жодного велосипеда з шаблону.
        blob = (space.persona.self_intro + guide.goal + guide.opening +
                " ".join(t.title for t in guide.topics)).lower()
        self.assertNotIn("велосипед", blob)
        self.assertIn("todo", space.persona.self_intro.lower())

    def test_new_space_rejects_duplicate(self):
        admin_api.create_space(self.root, "dup", "Раз")
        with self.assertRaises(admin_api.AdminError) as ctx:
            admin_api.create_space(self.root, "dup", "Два")
        self.assertEqual(ctx.exception.status, 409)

    def test_new_space_rejects_bad_key(self):
        for bad in ["../evil", "Має Пробіл", "", "a" * 60, "/etc"]:
            with self.assertRaises(admin_api.AdminError):
                admin_api.create_space(self.root, bad, "X")

    # ── запис ────────────────────────────────────────────────────────────
    def test_broken_guide_never_reaches_disk(self):
        before = admin_api.read_guide(self.root, "example", "first")
        broken = dict(before)
        broken["topics"] = [{"id": "a", "title": "A"}, {"id": "a", "title": "B"}]
        with self.assertRaises(admin_api.AdminError):
            admin_api.write_guide(self.root, "example", "first", broken)
        after = admin_api.read_guide(self.root, "example", "first")
        self.assertEqual(after["topics"], before["topics"], "зламаний гайд перезаписав робочий")

    def test_broken_space_never_reaches_disk(self):
        before = admin_api.read_space(self.root, "example")
        broken = dict(before)
        broken["privacy"] = {"deidentify": True, "never_ask_about": []}
        with self.assertRaises(admin_api.AdminError):
            admin_api.write_space(self.root, "example", broken)
        self.assertEqual(admin_api.read_space(self.root, "example")["privacy"], before["privacy"])

    def test_valid_guide_round_trip(self):
        data = admin_api.read_guide(self.root, "example", "first")
        data["goal"] = "Нова мета"
        data["topics"][0]["max_probes"] = 7
        admin_api.write_guide(self.root, "example", "first", data)
        again = admin_api.read_guide(self.root, "example", "first")
        self.assertEqual(again["goal"], "Нова мета")
        self.assertEqual(again["topics"][0]["max_probes"], 7)

    def test_write_guide_forces_key_to_match_filename(self):
        data = admin_api.read_guide(self.root, "example", "first")
        data["key"] = "щось-інше"
        admin_api.write_guide(self.root, "example", "first", data)
        self.assertEqual(admin_api.read_guide(self.root, "example", "first")["key"], "first")

    # ── читання ──────────────────────────────────────────────────────────
    def test_missing_guide_is_404(self):
        with self.assertRaises(admin_api.AdminError) as ctx:
            admin_api.read_guide(self.root, "example", "missing")
        self.assertEqual(ctx.exception.status, 404)

    def test_invalid_guide_key_is_400_not_404(self):
        """Невалідний ключ і відсутній файл — різні відповіді: інакше друкарська
        помилка в кирилиці виглядає як «гайд зник»."""
        with self.assertRaises(admin_api.AdminError) as ctx:
            admin_api.read_guide(self.root, "example", "немає")
        self.assertEqual(ctx.exception.status, 400)

    def test_listing_reports_draft_and_guides(self):
        admin_api.create_space(self.root, "draftone", "Чернетка")
        items = {item["key"]: item for item in admin_api.list_spaces(self.root)}
        self.assertFalse(items["example"]["draft"])
        self.assertTrue(items["draftone"]["draft"])
        self.assertIn("first", items["example"]["guides"])

    def test_listing_shows_broken_space_instead_of_hiding_it(self):
        path = os.path.join(self.root, "example", "space.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"key": "example"}, fh)
        entry = admin_api.list_spaces(self.root)[0]
        self.assertTrue(entry["error"], "зламаний простір зник зі списку замість показати помилку")


def post(base, path, payload):
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class TestAdminHttp(unittest.TestCase):
    """Адмінка вимкнена = її немає, а не «є, але закрита»."""

    @classmethod
    def setUpClass(cls):
        cls.space, cls.guide = load_space_dir(os.path.join(SPACES, "example"))
        cls.httpd = serve(cls.space, cls.guide, {"provider": "mock"}, port=0, admin_root=None)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_admin_api_absent_when_disabled(self):
        status, _ = post(self.base, "/api/admin/space/new", {"space": "x", "title": "X"})
        self.assertEqual(status, 404)

    def test_admin_page_absent_when_disabled(self):
        try:
            urllib.request.urlopen(self.base + "/admin", timeout=5)
            self.fail("сторінка адмінки віддалась при вимкненій адмінці")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 404)


class TestDraftBlocksInterview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.space, cls.guide = load_space_dir(os.path.join(SPACES, "example"))
        cls.space.draft = True
        cls.httpd = serve(cls.space, cls.guide, {"provider": "mock"}, port=0)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_draft_space_refuses_to_start(self):
        status, data = post(self.base, "/api/start", {})
        self.assertEqual(status, 409)
        self.assertIn("чернетка", data["error"])


if __name__ == "__main__":
    unittest.main()
