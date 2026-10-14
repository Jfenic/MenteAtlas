"""Synthetic fixtures generated in temporary private instances; no user data."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from matlasagent.cli import main
from matlasagent.library import Library, transcript
from matlasagent.parser import load_export, normalize
from matlasagent.storage import LibraryError, encoded, write_lock


def conversation(cid="c1", text="Decisión: construir un atlas local."):
    return {"id": cid, "title": "CON: Atlas / ejemplo ficticio", "create_time": 1700000000,
            "update_time": 1700000001, "mapping": {
                "root": {"parent": None, "children": ["node-1", "node-2"], "message": None},
                "node-1": {"parent": "root", "children": [], "message": {
                    "id": "m1", "author": {"role": "user"}, "create_time": 1700000000,
                    "content": {"content_type": "text", "parts": [text]}}},
                "node-2": {"parent": "root", "children": [], "message": {
                    "id": "m2", "author": {"role": "assistant"}, "create_time": 1700000001,
                    "content": {"content_type": "text", "parts": ["Propuesta ficticia para Obsidian."]}}}}}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.library = Library.initialize(self.base / "instance", self.base / "vault")

    def export(self, items, name="sample.json"):
        path = self.base / name
        path.write_bytes(encoded(items))
        return path

    def test_100_conversations_idempotence_and_original(self):
        path = self.export([conversation(f"chat-{i}") for i in range(100)])
        first = self.library.import_export(path)
        second = self.library.import_export(path)
        self.assertEqual(first["new_conversations"], 100)
        self.assertEqual(first["new_messages"], 200)
        self.assertEqual(second["new_messages"], 0)
        self.assertEqual(second["unchanged_messages"], 200)
        self.assertEqual(self.library.stats()["messages"], 200)
        self.assertEqual(len(list(self.library.vault.rglob("*.md"))), 100)
        self.assertEqual(next((self.library.root / "originals").iterdir()).read_bytes(), path.read_bytes())

    def test_incremental_versions_and_no_implicit_deletion(self):
        self.library.import_export(self.export([conversation()]))
        item = conversation(text="Decisión actualizada: atlas privado.")
        item["mapping"].pop("node-2")
        item["mapping"]["root"]["children"] = ["node-1"]
        counts = self.library.import_export(self.export([item]))
        self.assertEqual(counts["updated_messages"], 1)
        self.assertEqual(self.library.stats()["messages"], 2)
        self.assertEqual(self.library.stats()["message_versions"], 3)
        self.assertEqual(self.library.search("privado")[0]["version"], 2)
        self.assertEqual(len(self.library.search("Obsidian")), 1)

    def test_search_accents_phrases_filters_and_citations(self):
        self.library.import_export(self.export([conversation()]))
        row = self.library.search('"atlas local"', role="user", since=1699999999, until=1700000001)[0]
        self.assertEqual(row["message_id"], "m1")
        self.assertEqual(row["conversation_id"], "c1")
        self.assertIn("^" + row["anchor"], Path(row["note_path"]).read_text(encoding="utf-8"))
        self.assertTrue(Path(row["source_file"]).exists())
        self.assertEqual(len(self.library.search("decision")), 1)
        self.assertEqual(self.library.search("atlas", role="assistant"), [])
        self.assertEqual(self.library.search("atlas", offset=1), [])
        with self.assertRaises(LibraryError):
            self.library.search('"')
        with self.assertRaises(LibraryError):
            self.library.search("atlas", limit=101)

    def test_human_edits_preserved_conflict_and_reimport(self):
        self.library.import_export(self.export([conversation()]))
        note = next(self.library.vault.rglob("*.md"))
        edited = note.read_bytes() + "\nMi edición humana.\n".encode()
        note.write_bytes(edited)
        counts = self.library.import_export(self.export([conversation(text="Nueva idea ficticia.")]))
        self.assertEqual(counts["conflicts"], 1)
        self.assertEqual(note.read_bytes(), edited)
        self.assertEqual(len(list((self.library.root / "conflicts").glob("*.md"))), 1)
        self.library.import_export(self.export([conversation(text="Nueva idea ficticia.")]))
        self.assertEqual(note.read_bytes(), edited)

    def test_rename_and_intentional_delete_respected(self):
        path = self.export([conversation()])
        self.library.import_export(path)
        note = next(self.library.vault.rglob("*.md"))
        moved = self.library.vault / "renamed.MD"
        note.rename(moved)
        self.library.import_export(path)
        self.assertEqual(Path(self.library.search("atlas")[0]["note_path"]), moved)
        moved.unlink()
        counts = self.library.import_export(path)
        self.assertEqual(counts["missing_notes"], 1)
        self.assertEqual(list(self.library.vault.rglob("*.md")), [])
        self.assertIsNone(self.library.search("atlas")[0]["note_uri"])

    def test_index_rebuild_after_deletion_and_rollback(self):
        self.library.import_export(self.export([conversation()]))
        self.library.db.unlink()
        self.assertEqual(self.library.rebuild()["messages"], 2)
        source = self.library.source_files()[0]
        original = source.read_bytes()
        source.write_bytes(b"invalid")
        with self.assertRaises(json.JSONDecodeError):
            self.library.rebuild()
        self.assertEqual(self.library.stats()["messages"], 2)
        source.write_bytes(original)
        self.library.rebuild()

    def test_interrupted_note_checkpoint_can_resume(self):
        path = self.export([conversation()])
        import matlasagent.library as module
        writer = module.atomic_write
        def interrupt(target, data):
            if target.parent.name == "sources":
                raise OSError("simulated interruption")
            return writer(target, data)
        with patch.object(module, "atomic_write", side_effect=interrupt):
            with self.assertRaises(OSError):
                self.library.import_export(path)
        self.assertEqual(len(list(self.library.vault.rglob("*.md"))), 1)
        self.library.import_export(path)
        self.assertEqual(self.library.stats()["messages"], 2)
        self.assertEqual(len(list(self.library.vault.rglob("*.md"))), 1)

    def test_two_independent_instances(self):
        second = Library.initialize(self.base / "other-instance", self.base / "other-vault")
        self.library.import_export(self.export([conversation()]))
        self.assertEqual(second.stats()["messages"], 0)
        self.assertNotEqual(self.library.instance_id, second.instance_id)

    def test_git_and_overlapping_paths_rejected(self):
        repo = self.base / "repo"
        repo.mkdir()
        (repo / ".git").write_text("gitdir: fake", encoding="utf-8")
        with self.assertRaises(LibraryError):
            Library.initialize(repo / "data", self.base / "another-vault")
        with self.assertRaises(LibraryError):
            Library.initialize(self.base / "nested", self.base / "nested" / "vault")
        (self.library.vault / "existing.md").write_text("Synthetic note", encoding="utf-8")
        with self.assertRaises(LibraryError):
            Library.initialize(self.base / "new", self.library.vault)

    def test_zip_and_unsafe_entries(self):
        path = self.base / "sample.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("conversations.json", encoded([conversation()]))
        self.assertEqual(self.library.import_export(path)["new_messages"], 2)
        for unsafe in ("../escape", "C:/escape", "\\rooted"):
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("conversations.json", b"[]")
                archive.writestr(unsafe, b"unsafe")
            with self.assertRaises(LibraryError):
                load_export(path)

    def test_zip_symlink_bomb_duplicate_and_invalid(self):
        path = self.base / "sample.zip"
        link = zipfile.ZipInfo("link")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("conversations.json", b"[]")
            archive.writestr(link, b"elsewhere")
        with self.assertRaises(LibraryError):
            load_export(path)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("conversations.json", b" " * 1_000_000)
        with self.assertRaises(LibraryError):
            load_export(path)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("a/conversations.json", b"[]")
            archive.writestr("b/conversations.json", b"[]")
        with self.assertRaises(LibraryError):
            load_export(path)
        path.write_bytes(b"not a zip")
        with self.assertRaises(LibraryError):
            load_export(path)

    def test_invalid_json_empty_and_partial_input(self):
        path = self.export([])
        self.assertEqual(self.library.import_export(path)["new_messages"], 0)
        for payload in (b"", b"{}", b"[{\"id\":\"a\",\"id\":\"b\"}]", b"[NaN]"):
            path.write_bytes(payload)
            with self.assertRaises(LibraryError):
                load_export(path)
        counts = self.library.import_export(self.export([{}, conversation()]))
        self.assertEqual(counts["errors"], 1)
        self.assertEqual(counts["status"], "partial")
        self.assertEqual(self.library.stats()["messages"], 2)

    def test_branches_and_nontext_and_cycles(self):
        item = conversation()
        item["mapping"]["node-2"]["message"]["content"]["parts"].append({"image": "synthetic"})
        data, warnings = normalize(item)
        self.assertEqual(warnings, 1)
        self.assertEqual(data["nodes"]["root"]["children"], ["node-1", "node-2"])
        self.assertIn(b"Non-text", transcript(data))
        item["mapping"]["root"]["parent"] = "node-1"
        with self.assertRaises(LibraryError):
            normalize(item)

    def test_duplicate_message_ids_and_conversation_ids(self):
        item = conversation()
        item["mapping"]["node-2"]["message"]["id"] = "m1"
        with self.assertRaises(LibraryError):
            normalize(item)
        counts = self.library.import_export(self.export([conversation(), conversation()]))
        self.assertEqual(counts["errors"], 1)
        self.assertEqual(self.library.stats()["messages"], 2)

    def test_second_writer_rejected_and_lock_released(self):
        with write_lock(self.library.root):
            with self.assertRaises(LibraryError):
                Library(self.library.root).rebuild()
        self.library.rebuild()

    def test_cli_import_output_does_not_include_contents(self):
        text = "SYNTHETIC-CONTENT-NOT-FOR-LOGS"
        path = self.export([conversation(text=text)])
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            code = main(["--instance", str(self.library.root), "import", str(path)])
        self.assertEqual(code, 0)
        self.assertNotIn(text, output.getvalue())
        with redirect_stdout(output), redirect_stderr(output):
            self.assertEqual(main(["--instance", str(self.base / "missing"), "stats"]), 2)

    def test_source_and_vault_links_cannot_escape(self):
        target = self.base / "outside"
        target.mkdir()
        try:
            (self.library.vault / "linked").symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink creation requires OS permission")
        with self.assertRaises(LibraryError):
            self.library.rebuild()


if __name__ == "__main__":
    unittest.main()
