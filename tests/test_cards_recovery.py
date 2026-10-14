"""Canonical edits, provenance, safe replacement and complete restoration with synthetic data."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from matlasagent import cards, recovery
from matlasagent.cli import main
from matlasagent.library import Library
from matlasagent.storage import LibraryError, digest, encoded, write_lock
from test_core import conversation


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.library = Library.initialize(self.base / "instance", self.base / "vault")
        self.export = self.base / "synthetic.json"
        self.export.write_bytes(encoded([conversation()]))
        self.library.import_export(self.export)

    def card(self, **kwargs):
        return self.library.create_card("Idea ficticia", body="Contenido editable de la biblioteca.", **kwargs)

    def backup(self):
        path = self.base / "complete.zip"
        self.library.backup(path)
        return path

    def rewrite_archive(self, path, changes, *, update_checksums=False, extra=None):
        with zipfile.ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        files.update(changes)
        if update_checksums:
            manifest = json.loads(files["manifest.json"])
            for entry in manifest["files"]:
                if entry["path"] in changes:
                    entry.update(size=len(files[entry["path"]]), sha256=digest(files[entry["path"]]))
            files["manifest.json"] = encoded(manifest)
        if extra:
            files.update(extra)
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)

    def test_manual_and_excerpt_cards_multiple_sources(self):
        card = self.library.create_card("Decisión ficticia", kind="decision", sources=[("c1", "m1"), ("c1", "m2")], from_sources=True)
        read = self.library.get_card(card["id"])
        self.assertEqual(read["metadata"]["status"], "draft")
        self.assertEqual(read["metadata"]["origin"], "source_excerpt")
        self.assertIsNone(read["metadata"]["reviewed_by"])
        self.assertIn("construir un atlas", read["body"])
        self.assertEqual([r["role"] for r in read["citations"]], ["user", "assistant"])
        self.assertTrue(all(r["available"] for r in read["citations"]))
        manual = self.card()
        self.assertEqual(manual["sources"], [])

    def test_source_version_survives_reimport_without_changing_card(self):
        card = self.library.create_card("Idea", sources=[("c1", "m1")], from_sources=True)
        before = Path(card["path"]).read_bytes()
        self.export.write_bytes(encoded([conversation(text="Fuente actualizada y diferente.")]))
        self.library.import_export(self.export)
        read = self.library.get_card(card["id"])
        self.assertEqual(read["citations"][0]["version"], 1)
        self.assertIn("atlas local", read["citations"][0]["text"])
        self.assertEqual(Path(card["path"]).read_bytes(), before)

    def test_edits_moves_deletes_detected_without_regeneration(self):
        card = self.card()
        path = Path(card["path"])
        path.write_bytes(path.read_bytes() + "\nEdición humana: búsqueda ágil.\n".encode())
        moved = self.library.vault / "Otra carpeta" / "mi-nota.md"
        moved.parent.mkdir()
        path.rename(moved)
        row = self.library.search_cards('"busqueda agil"')[0]
        self.assertEqual(row["id"], card["id"])
        self.assertEqual(Path(row["note_path"]), moved)
        self.library.import_export(self.export)
        self.assertFalse(path.exists())
        self.assertIn("Edición humana", moved.read_text(encoding="utf-8"))
        moved.unlink()
        self.library.import_export(self.export)
        self.assertEqual(self.library.search_cards("biblioteca"), [])
        with self.assertRaises(LibraryError):
            self.library.get_card(card["id"])

    def test_filters_review_and_pagination(self):
        card = self.card(kind="decision", tags=["proyectos/atlas"])
        self.card(kind="information")
        reviewed = self.library.update_card(card["id"], expected_hash=card["content_hash"], status="reviewed", reviewer="human-local")
        rows = self.library.search_cards("biblioteca", kind="decision", status="reviewed", tag="proyectos/atlas")
        self.assertEqual([row["id"] for row in rows], [card["id"]])
        self.assertEqual(len(self.library.search_cards(limit=1, offset=1)), 1)
        self.assertEqual(self.library.search_cards(tag="missing"), [])
        self.assertEqual(self.library.search_cards(since=253402300799), [])
        edited = self.library.update_card(card["id"], expected_hash=reviewed["content_hash"], body="Nueva revisión necesaria.")
        self.assertEqual(edited["status"], "draft")
        with self.assertRaises(LibraryError):
            self.library.update_card(card["id"], expected_hash=edited["content_hash"], status="reviewed")

    def test_stale_card_edit_preserves_both_and_requires_current_hash(self):
        card = self.card()
        path = Path(card["path"])
        changed = path.read_bytes() + b"\nExternal edit.\n"
        path.write_bytes(changed)
        result = self.library.update_card(card["id"], expected_hash=card["content_hash"], body="Proposed content.")
        self.assertTrue(result["conflict"])
        self.assertEqual(path.read_bytes(), changed)
        conflicts = self.library.list_conflicts()
        self.assertEqual(len(conflicts), 1)
        with self.assertRaises(LibraryError):
            self.library.resolve_conflict(result["proposal"], action="apply", expected_hash=card["content_hash"])
        self.library.resolve_conflict(result["proposal"], action="apply", expected_hash=digest(changed))
        self.assertEqual(self.library.get_card(card["id"])["body"], "Proposed content.")
        self.assertEqual(self.library.list_conflicts(), [])
        self.assertEqual(next((self.library.root / "resolved_versions").glob("*.md")).read_bytes(), changed)

    def test_keep_current_does_not_change_human_note(self):
        card = self.card()
        path = Path(card["path"])
        before = path.read_bytes()
        proposal = self.library.update_card(card["id"], expected_hash="outdated", body="Other version.")
        self.library.resolve_conflict(proposal["proposal"], action="keep")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.library.list_conflicts(), [])

    def test_keep_deleted_card_respects_deletion(self):
        card = self.card()
        proposal = self.library.update_card(card["id"], expected_hash="outdated", body="Pending change.")
        Path(card["path"]).unlink()
        with self.assertRaises(LibraryError):
            self.library.resolve_conflict(proposal["proposal"], action="apply", expected_hash=card["content_hash"])
        self.library.resolve_conflict(proposal["proposal"], action="keep")
        self.assertEqual(self.library.list_conflicts(), [])
        self.assertEqual(self.library.stats()["cards"], 0)

    def test_transcript_conflict_applies_only_current_proposal(self):
        path = next((self.library.vault / "Conversations").glob("*.md"))
        path.write_bytes(path.read_bytes() + b"\nPersonal annotation.\n")
        self.export.write_bytes(encoded([conversation(text="Version two.")]))
        self.library.import_export(self.export)
        first = self.library.list_conflicts()[0]
        self.export.write_bytes(encoded([conversation(text="Version three.")]))
        self.library.import_export(self.export)
        with self.assertRaises(LibraryError):
            self.library.resolve_conflict(first["proposal"], action="apply", expected_hash=digest(path.read_bytes()))
        self.library.resolve_conflict(first["proposal"], action="keep")
        current = self.library.list_conflicts()[0]
        self.library.resolve_conflict(current["proposal"], action="apply", expected_hash=digest(path.read_bytes()))
        self.assertIn("Version three.", path.read_text(encoding="utf-8"))
        self.assertEqual(self.library.import_export(self.export)["conflicts"], 0)

    def test_invalid_sources_and_types_do_not_create_cards(self):
        for kwargs in ({"sources": [("missing", "m1")]}, {"kind": "preference"},
                       {"sources": [("c1", "m1"), ("c1", "m1")]}, {"from_sources": True}):
            with self.assertRaises(LibraryError):
                self.card(**kwargs)
        self.assertEqual(self.library.stats()["cards"], 0)

    def test_card_body_and_reference_limits(self):
        with self.assertRaises(LibraryError):
            self.library.create_card("Too many sources", sources=[("c1", "m1")] * 101, from_sources=True)
        with self.assertRaises(LibraryError):
            self.library.create_card("Too much content", body="x" * (cards.MAX_CARD + 1))
        self.export.write_bytes(encoded([conversation(text="x" * 2000)]))
        self.library.import_export(self.export)
        with patch.object(cards, "MAX_CARD", 512):
            with self.assertRaises(LibraryError):
                self.library.create_card("Too large excerpt", sources=[("c1", "m1")], from_sources=True)
        self.assertEqual(self.library.stats()["cards"], 0)

    def test_duplicate_ids_invalid_yaml_and_aliases_leave_index_intact(self):
        card = self.card()
        path = Path(card["path"])
        duplicate = self.library.vault / "duplicate.md"
        duplicate.write_bytes(path.read_bytes())
        with self.assertRaises(LibraryError):
            self.library.rebuild()
        self.assertEqual(self.library.stats()["cards"], 1)
        duplicate.unlink()
        original = path.read_bytes()
        for raw in (b"---\nmatlas_kind: card\n!!python/object:unsafe {}\n---\ntext",
                    b"---\nmatlas_kind: card\ntags: &a [*a]\n---\ntext",
                    b"---\nmatlas_kind: card\nid: one\nid: two\n---\ntext"):
            path.write_bytes(raw)
            with self.assertRaises(LibraryError):
                self.library.rebuild()
            self.assertEqual(self.library.stats()["cards"], 1)
        path.write_bytes(original)
        self.library.rebuild()

    def test_decisions_successors_and_cycle_rejection(self):
        old = self.card(kind="decision")
        successor = self.card(kind="decision")
        self.library.update_card(old["id"], expected_hash=old["content_hash"], superseded_by=successor["id"])
        with self.assertRaises(LibraryError):
            self.library.update_card(successor["id"], expected_hash=successor["content_hash"], superseded_by=old["id"])
        with self.assertRaises(LibraryError):
            self.library.update_card(successor["id"], expected_hash=successor["content_hash"], superseded_by=successor["id"])

    def test_obisidian_yaml_conversion_keeps_transcript_id(self):
        from matlasagent.library import note_header
        import yaml
        path = next((self.library.vault / "Conversations").glob("*.md"))
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        metadata = json.loads(lines[1])
        path.write_text("---\n" + yaml.safe_dump(metadata) + "---\n" + "".join(lines[3:]), encoding="utf-8")
        self.assertEqual(note_header(path)["conversation_id"], "c1")
        self.library.rebuild()
        self.assertEqual(self.library.search("atlas")[0]["note_path"], str(path))

    def test_migration_from_delivery_one_preserves_messages(self):
        connection = self.library.connect()
        connection.executescript("DROP TABLE tag_assignments; DROP TABLE tags; DROP TABLE card_fts; DROP TABLE cards; PRAGMA user_version=1;")
        connection.close()
        connection = self.library.connect()
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
        self.assertEqual(connection.execute("SELECT count(*) FROM messages").fetchone()[0], 2)
        connection.close()

    def test_complete_backup_and_restore_to_different_locations(self):
        card = self.library.create_card("Idea", sources=[("c1", "m1")], from_sources=True)
        path = Path(card["path"])
        path.write_bytes(path.read_bytes() + b"\nHuman edit to keep.\n")
        moved = self.library.vault / "moved.md"
        path.rename(moved)
        # Durable operational files unknown to the current version must also survive.
        (self.library.root / "future-tags.json").write_bytes(b'{"approved": ["atlas"]}')
        (self.library.vault / ".obsidian").mkdir()
        (self.library.vault / ".obsidian" / "app.json").write_bytes(b"{}")
        proposal = self.library.update_card(card["id"], expected_hash=card["content_hash"], body="Pending proposal.")
        archive = self.backup()
        with zipfile.ZipFile(archive) as backup:
            self.assertNotIn("instance/index.sqlite3", backup.namelist())
            self.assertNotIn("instance/writer.lock", backup.namelist())
        result = Library.restore(archive, self.base / "restored-instance", self.base / "restored-vault")
        restored = Library(self.base / "restored-instance")
        self.assertTrue(result["restored"])
        self.assertNotEqual(restored.instance_id, self.library.instance_id)
        self.assertEqual(restored.get_card(card["id"])["content_hash"], digest(moved.read_bytes()))
        self.assertEqual(restored.list_conflicts()[0]["proposal"], proposal["proposal"])
        self.assertEqual((restored.root / "future-tags.json").read_bytes(), b'{"approved": ["atlas"]}')
        self.assertTrue((restored.vault / ".obsidian" / "app.json").exists())
        citation = restored.get_card(card["id"])["citations"][0]
        self.assertTrue(Path(citation["source_file"]).is_relative_to(restored.root))
        self.assertTrue(Path(citation["note_path"]).is_relative_to(restored.vault))
        self.assertEqual(restored.stats(), self.library.stats())

    def test_deleted_notes_stay_deleted_after_restore(self):
        card = self.card()
        Path(card["path"]).unlink()
        next((self.library.vault / "Conversations").glob("*.md")).unlink()
        archive = self.backup()
        Library.restore(archive, self.base / "restored", self.base / "restored-vault")
        restored = Library(self.base / "restored")
        self.assertEqual(restored.stats()["cards"], 0)
        self.assertIsNone(restored.search("atlas")[0]["note_path"])
        restored.import_export(self.export)
        self.assertEqual(list(restored.vault.rglob("*.md")), [])

    def test_backup_refuses_existing_inside_git_and_nested_destinations(self):
        archive = self.backup()
        before = archive.read_bytes()
        for path in (archive, self.library.root / "bad.zip", self.library.vault / "bad.zip"):
            with self.assertRaises(LibraryError):
                self.library.backup(path)
        repo = self.base / "git-repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        with self.assertRaises(LibraryError):
            self.library.backup(repo / "bad.zip")
        self.assertEqual(archive.read_bytes(), before)

    def test_restore_never_overwrites_existing_data(self):
        archive = self.backup()
        for instance, vault in ((self.library.root, self.base / "new-vault"),
                                (self.base / "new-instance", self.library.vault),
                                (self.base / "overlap", self.base / "overlap" / "vault")):
            with self.assertRaises(LibraryError):
                Library.restore(archive, instance, vault)
        self.assertEqual(self.library.stats()["messages"], 2)

    def test_restore_empty_directories_and_archive_limits(self):
        archive = self.backup()
        root, vault = self.base / "restored", self.base / "restored-vault"
        root.mkdir()
        vault.mkdir()
        with patch.object(recovery, "MAX_FILES", 1):
            with self.assertRaises(LibraryError):
                Library.restore(archive, root, vault)
        self.assertEqual(list(root.iterdir()), [])
        self.assertEqual(list(vault.iterdir()), [])
        self.assertTrue(Library.restore(archive, root, vault)["restored"])

    def test_interrupted_publication_retains_vault_and_original_backup(self):
        archive = self.backup()
        publisher = recovery.publish_stage
        calls = 0
        def interrupt(stage, target):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated publication interruption")
            return publisher(stage, target)
        with patch.object(recovery, "publish_stage", side_effect=interrupt):
            with self.assertRaises(LibraryError):
                Library.restore(archive, self.base / "restored", self.base / "restored-vault")
        self.assertTrue(archive.exists())
        self.assertTrue(any((self.base / "restored-vault").rglob("*.md")))
        self.assertEqual(self.library.stats()["messages"], 2)

    def test_corrupted_payload_rejected_before_publication(self):
        card = self.card()
        archive = self.backup()
        name = "vault/" + Path(card["path"]).relative_to(self.library.vault).as_posix()
        content = Path(card["path"]).read_bytes()
        self.rewrite_archive(archive, {name: content.replace(b"Contenido", b"Alterado!")})
        with self.assertRaises(LibraryError):
            Library.restore(archive, self.base / "restored", self.base / "restored-vault")
        self.assertFalse((self.base / "restored").exists())
        self.assertFalse((self.base / "restored-vault").exists())
        self.assertEqual(list(self.base.glob(".matlas-restore-*")), [])

    def test_restore_rejects_unlisted_traversal_symlinks_and_duplicates(self):
        archive = self.backup()
        original = archive.read_bytes()
        for extra in ({"../escape": b"unsafe"}, {"vault/extra.txt": b"unlisted"}, {"vault/CON.txt": b"unsafe"}):
            archive.write_bytes(original)
            self.rewrite_archive(archive, {}, extra=extra)
            with self.assertRaises(LibraryError):
                Library.restore(archive, self.base / "restored", self.base / "restored-vault")
        archive.write_bytes(original)
        link = zipfile.ZipInfo("vault/link")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        with zipfile.ZipFile(archive, "a") as writer:
            writer.writestr(link, b"elsewhere")
        with self.assertRaises(LibraryError):
            Library.restore(archive, self.base / "restored", self.base / "restored-vault")
        archive.write_bytes(original)
        with zipfile.ZipFile(archive, "a") as writer:
            writer.writestr("MANIFEST.json", b"{}")
        with self.assertRaises(LibraryError):
            Library.restore(archive, self.base / "restored", self.base / "restored-vault")

    def test_backup_detects_editor_change_and_leaves_no_partial_archive(self):
        card = self.card()
        path = Path(card["path"])
        original = recovery.hash_stream
        def mutate(stream, output=None):
            result = original(stream, output)
            if Path(stream.name) == path:
                path.write_bytes(path.read_bytes() + b"\nChanged during snapshot.\n")
            return result
        with patch.object(recovery, "hash_stream", side_effect=mutate):
            with self.assertRaises(LibraryError):
                self.library.backup(self.base / "complete.zip")
        self.assertFalse((self.base / "complete.zip").exists())
        self.assertEqual(list(self.base.glob(".pending-backup-*")), [])

    def test_source_original_integrity_check_on_backup(self):
        original = next((self.library.root / "originals").iterdir())
        original.write_bytes(b"corrupted original")
        with self.assertRaises(LibraryError):
            self.library.backup(self.base / "bad.zip")
        self.assertFalse((self.base / "bad.zip").exists())

    def test_valid_checksum_invalid_card_and_missing_original_rejected(self):
        card = self.card()
        archive = self.backup()
        original = archive.read_bytes()
        name = "vault/" + Path(card["path"]).relative_to(self.library.vault).as_posix()
        self.rewrite_archive(archive, {name: b"---\nmatlas_kind: card\n---\ninvalid"}, update_checksums=True)
        with self.assertRaises(LibraryError):
            Library.restore(archive, self.base / "restored", self.base / "restored-vault")
        self.assertFalse((self.base / "restored-vault").exists())
        archive.write_bytes(original)
        source = self.library.source_files()[0]
        record = json.loads(source.read_text(encoding="utf-8"))
        record["original_hash"] = "0" * 64
        self.rewrite_archive(archive, {"instance/sources/" + source.name: encoded(record)}, update_checksums=True)
        with self.assertRaises(LibraryError):
            Library.restore(archive, self.base / "restored", self.base / "restored-vault")
        self.assertFalse((self.base / "restored").exists())

    def test_writer_lock_blocks_backup_and_card_changes(self):
        with write_lock(self.library.root):
            with self.assertRaises(LibraryError):
                Library(self.library.root).backup(self.base / "bad.zip")
            with self.assertRaises(LibraryError):
                Library(self.library.root).create_card("blocked")

    def test_cli_create_search_backup_restore_and_conflict_exit(self):
        output = io.StringIO()
        args = ["--instance", str(self.library.root)]
        with redirect_stdout(output), redirect_stderr(output):
            self.assertEqual(main(args + ["card", "create", "--title", "CLI example", "--source", "c1", "m1", "--from-sources"]), 0)
        card = json.loads(output.getvalue())
        self.assertNotIn("atlas local", output.getvalue())
        output.seek(0)
        output.truncate()
        with redirect_stdout(output), redirect_stderr(output):
            self.assertEqual(main(args + ["search", "atlas", "--scope", "cards"]), 0)
        self.assertEqual(json.loads(output.getvalue())[0]["id"], card["id"])
        output.seek(0)
        output.truncate()
        with redirect_stdout(output), redirect_stderr(output):
            self.assertEqual(main(args + ["card", "update", card["id"], "--expect-hash", "stale", "--title", "Other title"]), 2)
        archive = self.base / "cli-backup.zip"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(args + ["backup", str(archive)]), 0)
            self.assertEqual(main(["--instance", str(self.base / "new-instance"), "restore", str(archive),
                                   "--vault", str(self.base / "new-vault")]), 0)
        self.assertEqual(Library(self.base / "new-instance").stats()["cards"], 1)


if __name__ == "__main__":
    unittest.main()
