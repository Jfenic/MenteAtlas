"""Protected loopback transport and lifecycle, exclusively synthetic libraries."""
from http.client import HTTPConnection
from importlib.resources import files
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from matlasagent.api import LocalServer, open_library
from matlasagent.library import Library
from matlasagent.storage import LibraryError


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.library = Library.initialize(self.base / "instance", self.base / "vault")
        self.token = "a" * 64
        self.server = LocalServer(self.library, self.token)
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01})
        self.worker.start()
        def stop():
            self.server.shutdown()
            self.worker.join(10)
            self.server.server_close()
        self.addCleanup(stop)

    def request(self, method, endpoint, data=None, headers=None, raw=None):
        auth = {"Authorization": "Bearer " + self.token}
        body = raw
        if data is not None:
            body = json.dumps(data).encode()
            auth["Content-Type"] = "application/json"
        auth.update(headers or {})
        client = HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            client.request(method, endpoint, body=body, headers=auth)
            response = client.getresponse()
            result = json.loads(response.read())
            return response.status, result
        finally:
            client.close()

    def test_auth_host_origin_and_no_cors(self):
        for headers, status in (({"Authorization": "wrong"}, 401), ({"Origin": "https://example.org"}, 403),
                                ({"Host": "example.org"}, 403)):
            code, result = self.request("GET", "/stats", headers=headers)
            self.assertEqual(code, status)
            self.assertNotIn(str(self.base), json.dumps(result))
        code, health = self.request("GET", "/health")
        self.assertEqual(code, 200)
        self.assertEqual(health["protocol"], 1)
        self.assertEqual(health["vault"], str(self.library.vault))
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def import_sample(self):
        return self.request("POST", "/import", raw=files("matlasagent").joinpath("synthetic-export.json").read_bytes(),
                            headers={"Content-Type": "application/octet-stream", "X-MAtlas-Format": "json"})

    def test_import_search_card_and_backup_contract(self):
        code, counts = self.import_sample()
        self.assertEqual(code, 200)
        self.assertEqual(counts["new_messages"], 2)
        self.assertFalse(list(self.library.root.glob(".pending-api-import-*")))
        code, rows = self.request("POST", "/search", {"scope": "messages", "query": "atlas", "limit": 10})
        self.assertEqual(code, 200)
        row = rows[0]
        self.assertTrue(row["vault_path"].startswith("Conversations/"))
        reference = {key: row[key] for key in ("source", "conversation_id", "message_id", "version")}
        code, card = self.request("POST", "/cards", {"title": "Ficha API", "sources": [reference], "from_sources": True})
        self.assertEqual(code, 200)
        self.assertTrue(card["vault_path"].startswith("Cards/"))
        code, cards = self.request("POST", "/search", {"scope": "cards", "query": ""})
        self.assertEqual(cards[0]["id"], card["id"])
        self.assertEqual(cards[0]["citations"][0]["version"], 1)
        target = self.base / "backup.zip"
        self.assertEqual(self.request("POST", "/backup", {"path": str(target)})[0], 200)
        restored = self.base / "restored"
        Library.restore(target, restored, self.base / "restored-vault")
        self.assertEqual(Library(restored).stats()["cards"], 1)

    def test_invalid_requests_never_echo_input_or_write_cards(self):
        marker = "SYNTHETIC_SECRET_NOT_FOR_LOGS"
        for endpoint, data in (("/cards", {"title": marker, "sources": "bad"}),
                               ("/cards", {"title": marker, "unexpected": True}),
                               ("/search", {"scope": "arbitrary", "query": marker}),
                               ("/search?token=" + marker, {}), ("/backup", {"path": 1})):
            code, output = self.request("POST", endpoint, data)
            self.assertEqual(code, 400)
            self.assertNotIn(marker, json.dumps(output))
        self.assertEqual(self.library.stats()["cards"], 0)
        self.assertEqual(self.request("POST", "/cards", raw=b"not-json", headers={"Content-Type": "application/json"})[0], 400)
        self.assertEqual(self.request("POST", "/cards", {}, headers={"Transfer-Encoding": "chunked"})[0], 400)
        self.assertEqual(self.request("GET", "/missing")[0], 404)

    def test_upload_limits_invalid_format_and_cleanup(self):
        headers = {"Content-Type": "application/octet-stream", "X-MAtlas-Format": "json"}
        self.assertEqual(self.request("POST", "/import", raw=b"x", headers={**headers, "Content-Length": str(65 * 1024 * 1024)})[0], 400)
        self.assertEqual(self.request("POST", "/import", raw=b"x", headers={**headers, "X-MAtlas-Format": "../json"})[0], 400)
        self.assertEqual(self.request("POST", "/import", raw=b"invalid", headers=headers)[0], 400)
        self.assertFalse(list(self.library.root.glob(".pending-api-import-*")))

    def test_vault_binding_and_safe_first_run(self):
        with self.assertRaises(LibraryError):
            open_library(self.library.root, self.base / "other-vault")
        vault = self.base / "new-vault"
        (vault / ".obsidian").mkdir(parents=True)
        config = vault / ".obsidian" / "app.json"
        config.write_text("{}")
        library = open_library(self.base / "new-instance", vault, initialize=True)
        self.assertEqual(library.vault, vault)
        self.assertEqual(config.read_text(), "{}")
        occupied = self.base / "occupied-vault"
        occupied.mkdir()
        (occupied / "private.md").write_text("Keep this synthetic note.")
        with self.assertRaises(LibraryError):
            open_library(self.base / "occupied-instance", occupied, initialize=True)
        self.assertFalse((self.base / "occupied-instance").exists())
        self.assertEqual((occupied / "private.md").read_text(), "Keep this synthetic note.")

    def test_child_handshake_and_parent_pipe_closure(self):
        child = subprocess.Popen([sys.executable, "-m", "matlasagent.api", "--instance", str(self.library.root),
                                  "--vault", str(self.library.vault)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        child.stdin.write(json.dumps({"token": self.token}).encode() + b"\n")
        child.stdin.flush()
        # Bound the read even if a regression prevents startup.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool:
            handshake = pool.submit(child.stdout.readline)
            try:
                line = handshake.result(timeout=20)
            except TimeoutError:
                child.kill()
                raise
        data = json.loads(line)
        self.assertEqual(data["protocol"], 1)
        self.assertNotIn(self.token.encode(), line)
        child.stdin.close()
        self.assertEqual(child.wait(timeout=10), 0)
        self.assertEqual(child.stderr.read(), b"")
        child.stdout.close()
        child.stderr.close()
