"""Два окремі сайти з одного коду: респондент не бачить адмінки, панель не віддає респондентських ендпоінтів."""

import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.server import SessionStore, make_handler
from app.config.space import load_space_dir

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _status(port, path, method="GET", host=None):
    headers = {"Content-Type": "application/json"}
    if host:
        headers["Host"] = host
    request = urllib.request.Request(
        "http://127.0.0.1:%d%s" % (port, path), method=method,
        data=b"{}" if method == "POST" else None, headers=headers)
    try:
        return urllib.request.urlopen(request).status
    except urllib.error.HTTPError as exc:
        return exc.code


class TestSurfaces(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        space, guide = load_space_dir(os.path.join(ROOT, "spaces", "example"))
        llm = {"provider": "mock"}
        cls.servers = []
        cls.ports = {}
        os.environ["ADMIN_HOSTS"] = "admin.example.test"
        for surface in ("respondent", "admin", "auto"):
            handler = make_handler(space, guide, llm, SessionStore(space, guide, llm, None),
                                   os.path.join(ROOT, "spaces"), None, surface)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            cls.servers.append(server)
            cls.ports[surface] = server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        for server in cls.servers:
            server.shutdown()
            server.server_close()

    def test_respondent_site_has_no_admin(self):
        port = self.ports["respondent"]
        self.assertEqual(_status(port, "/"), 200)
        self.assertEqual(_status(port, "/api/space"), 200)
        for path in ("/admin", "/admin.js", "/api/admin/spaces", "/api/sessions"):
            self.assertEqual(_status(port, path), 404, path)
        self.assertEqual(_status(port, "/api/admin/space", "POST"), 404)

    def test_admin_site_has_no_respondent_endpoints(self):
        port = self.ports["admin"]
        self.assertEqual(_status(port, "/"), 200)
        self.assertEqual(_status(port, "/api/admin/spaces"), 200)
        for path in ("/api/space", "/index.html", "/app.js"):
            self.assertEqual(_status(port, path), 404, path)
        self.assertEqual(_status(port, "/api/start", "POST"), 404)

    def test_auto_surface_picks_site_by_host(self):
        port = self.ports["auto"]
        # Домен із ADMIN_HOSTS — панель; усе інше (і унікальні адреси деплоїв) — лише респондент.
        self.assertEqual(_status(port, "/api/admin/spaces", host="admin.example.test"), 200)
        self.assertEqual(_status(port, "/api/space", host="admin.example.test"), 404)
        self.assertEqual(_status(port, "/api/admin/spaces", host="pv-123.vercel.app"), 404)
        self.assertEqual(_status(port, "/api/space", host="pv-123.vercel.app"), 200)


if __name__ == "__main__":
    unittest.main()
