"""Desktop orchestration with synthetic sources; no graphical display required."""
from importlib.resources import files
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from matlasagent.desktop import Session, create_demo, source_reference
from matlasagent.library import Library
from matlasagent.storage import LibraryError


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.session = Session()
        self.addCleanup(self.session.close)

    def test_demo_is_independent_repeatable_and_recoverable(self):
        with patch("matlasagent.desktop.default_instance", return_value=self.base / "data" / "default"):
            first = create_demo(self.base / "notes")
            second = create_demo(self.base / "notes")
        self.assertNotEqual(first.root, second.root)
        self.assertNotEqual(first.vault, second.vault)
        self.assertEqual(first.stats()["messages"], 2)
        self.assertFalse((first.root / "demo-input.json").exists())
        card = first.search_cards(tag="atlas")[0]
        self.assertEqual(card["citations"][0]["version"], 1)
        backup = self.base / "demo.zip"
        first.backup(backup)
        Library.restore(backup, self.base / "restored", self.base / "restored-vault")
        # Restore returns a summary, reopen as a client would.
        library = Library(self.base / "restored")
        self.assertEqual(library.search_cards(tag="atlas")[0]["id"], card["id"])

    def test_failed_open_keeps_the_previous_library(self):
        library = Library.initialize(self.base / "data", self.base / "notes")
        self.session.submit(lambda: self.session.open(library.root)).result(timeout=30)
        with self.assertRaises(LibraryError):
            self.session.submit(lambda: self.session.open(self.base / "missing")).result(timeout=30)
        self.assertEqual(self.session.library.root, library.root)
        self.assertEqual(self.session.submit(lambda: self.session.library.stats()).result(timeout=30)["messages"], 0)

    def test_jobs_do_not_overlap_and_failure_does_not_stop_the_worker(self):
        started, release = threading.Event(), threading.Event()
        order = []
        def first():
            started.set()
            if not release.wait(5):
                raise TimeoutError()
            order.append("first")
        initial = self.session.submit(first)
        self.assertTrue(started.wait(5))
        second = self.session.submit(lambda: order.append("second"))
        self.assertFalse(second.done())
        release.set()
        initial.result(timeout=5)
        second.result(timeout=5)
        self.assertEqual(order, ["first", "second"])
        broken = self.session.submit(lambda: (_ for _ in ()).throw(LibraryError("Synthetic failure")))
        with self.assertRaises(LibraryError):
            broken.result(timeout=5)
        self.assertEqual(self.session.submit(lambda: 42).result(timeout=5), 42)

    def test_selected_version_survives_a_later_import(self):
        import json
        library = Library.initialize(self.base / "data", self.base / "notes")
        source = self.base / "sample.json"
        data = json.loads(files("matlasagent").joinpath("synthetic-export.json").read_text(encoding="utf-8"))
        source.write_text(json.dumps(data), encoding="utf-8")
        library.import_export(source)
        row = library.search("atlas")[0]
        reference = source_reference(row)
        data[0]["mapping"]["node-user"]["message"]["content"]["parts"] = ["Texto posterior ficticio."]
        source.write_text(json.dumps(data), encoding="utf-8")
        library.import_export(source)
        card = library.create_card("Fuente elegida", sources=[reference], from_sources=True)
        detail = library.get_card(card["id"])
        self.assertEqual(detail["metadata"]["sources"][0]["version"], 1)
        self.assertIn("atlas local", detail["body"])
        self.assertNotIn("Texto posterior", detail["body"])
