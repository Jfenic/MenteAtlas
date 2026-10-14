"""Synthetic taxonomy, human overrides, rule review and durable restoration."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest

from matlasagent import cards
from matlasagent.cli import main
from matlasagent.library import Library
from matlasagent.storage import LibraryError, encoded
from matlasagent.tags import Catalog, normalize
from test_core import conversation


class TagTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.library = Library.initialize(self.base / "instance", self.base / "vault")
        self.export = self.base / "synthetic.json"
        self.export.write_bytes(encoded([conversation(text="Python y biblioteca local ficticia.")]))
        self.library.import_export(self.export)

    def register(self, slug, **kwargs):
        return self.library.tags("register", slug=slug, **kwargs)

    def python_tag(self):
        root = self.register("programacion", label="Programación")
        child = self.register("programacion/python", label="Python")
        self.library.tags("alias", alias="py", value=child["slug"])
        return root, child

    def card(self, body="Python y biblioteca ficticia.", **kwargs):
        return self.library.create_card("Ficha ficticia", body=body, **kwargs)

    def rule(self, slug="programacion/python", **kwargs):
        return self.library.tags("rule-add", slug=slug, terms=["python"], **kwargs)

    def pending(self):
        return self.library.tags("proposals", status="pending")

    def test_unicode_case_normalization_and_hierarchy(self):
        self.assertEqual(normalize("  Programación / ＰＹＴＨＯＮ "), "programación/python")
        self.assertEqual(normalize("Programacio\u0301n"), "programación")
        self.assertNotEqual(normalize("piñata"), normalize("pinata"))
        root = self.register("Programacio\u0301n")
        child = self.register("PROGRAMACIÓN/Python")
        self.assertEqual(child["parent_id"], root["id"])
        self.assertEqual(self.register("programación/python")["id"], child["id"])
        self.assertEqual(self.library.tags("tree")[0]["children"][0]["id"], child["id"])
        for invalid in ("../escape", "a//b", "a:b", "", "a/unknown/child"):
            with self.assertRaises(LibraryError):
                self.register(invalid)

    def test_suggestions_review_and_reuse_alias_before_creation(self):
        self.python_tag()
        reused = self.register("PY", proposed=True)
        self.assertEqual(reused["slug"], "programacion/python")
        proposal = self.register("proyecto-nuevo", proposed=True)
        with self.assertRaises(LibraryError):
            self.rule("proyecto-nuevo")
        rejected = self.library.tags("review", value=proposal["slug"], approve=False)
        self.assertEqual(self.register(proposal["slug"], proposed=True)["status"], "rejected")
        self.assertEqual(rejected["id"], proposal["id"])
        self.library.tags("review", value=proposal["slug"], approve=True)
        self.assertEqual(Catalog(self.library).require(proposal["slug"])["status"], "approved")

    def test_alias_collision_and_invalid_redirects(self):
        self.python_tag()
        self.register("otro")
        for alias in ("PY", "programacion"):
            with self.assertRaises(LibraryError):
                self.library.tags("alias", alias=alias, value="otro")
        self.library.tags("alias", alias="Lenguaje Python", value="py")
        self.assertEqual(Catalog(self.library).require("lenguaje python")["slug"], "programacion/python")
        self.assertEqual(len(self.library.tags("list")), 3)

    def test_existing_freeform_card_tags_become_protected_only_after_approval(self):
        card = self.card(tags=["Python", "unknown tag!"])
        before = Path(card["path"]).read_bytes()
        self.assertEqual(self.library.tags("list"), [])
        self.python_tag()
        self.library.tags("alias", alias="python", value="py")
        records = self.library.tags("assignments", target={"kind": "card", "card_id": card["id"]})
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["locked_by_user"])
        self.assertEqual(records[0]["origin"], "manual")
        self.assertEqual(Path(card["path"]).read_bytes(), before)
        self.assertEqual(self.library.search_cards("biblioteca", tag="py")[0]["id"], card["id"])
        self.assertEqual(len(self.library.search_cards(tag="unknown tag!")), 1)

    def test_rule_matching_is_reviewable_idempotent_and_never_creates_vocabulary(self):
        self.python_tag()
        card = self.card()
        rule = self.rule()
        self.assertEqual(self.rule()["id"], rule["id"])
        counts = self.library.tags("classify")
        self.assertEqual(counts["new_proposals"], 1)
        self.assertEqual(self.library.tags("classify")["new_proposals"], 0)
        self.assertEqual(len(self.pending()), 1)
        self.assertEqual(self.library.get_card(card["id"])["metadata"]["tags"], [])
        self.assertEqual(len(self.library.tags("list")), 2)
        proposal = self.pending()[0]
        self.library.tags("review-proposal", proposal_id=proposal["id"], approve=True, expected_hash=card["content_hash"])
        record = self.library.tags("assignments", target={"kind": "card", "card_id": card["id"]})[0]
        self.assertEqual(record["origin"], "rule")
        self.assertFalse(record["locked_by_user"])
        self.assertEqual(self.library.search_cards(tag="programacion")[0]["id"], card["id"])
        self.assertEqual(self.library.tags("classify")["new_proposals"], 0)

    def test_rejection_persists_across_changes_and_reimports(self):
        self.python_tag()
        card = self.card()
        self.rule()
        self.library.tags("classify")
        proposal = self.pending()[0]
        self.library.tags("review-proposal", proposal_id=proposal["id"], approve=False)
        path = Path(card["path"])
        path.write_bytes(path.read_bytes() + b"\nPython remains present.\n")
        self.library.import_export(self.export)
        self.assertEqual(self.library.tags("classify")["new_proposals"], 0)
        self.assertEqual(self.library.get_card(card["id"])["metadata"]["tags"], [])
        record = self.library.tags("assignments")[0]
        self.assertEqual(record["state"], "blocked")
        self.assertTrue(record["locked_by_user"])

    def test_external_removal_of_rule_tag_becomes_human_block(self):
        self.python_tag()
        card = self.card()
        self.rule()
        self.library.tags("classify")
        proposal = self.pending()[0]
        self.library.tags("review-proposal", proposal_id=proposal["id"], approve=True, expected_hash=card["content_hash"])
        path = Path(card["path"])
        current = cards.read(path)
        current["metadata"]["tags"] = []
        path.write_bytes(cards.render(current["metadata"], current["body"]))
        self.assertEqual(self.library.tags("classify")["new_proposals"], 0)
        record = self.library.tags("assignments")[0]
        self.assertEqual(record["origin"], "manual")
        self.assertEqual(record["state"], "blocked")
        self.assertEqual(self.library.search_cards(tag="py"), [])

    def test_external_alias_edit_locks_an_accepted_rule_assignment(self):
        self.python_tag()
        card = self.card()
        self.rule()
        self.library.tags("classify")
        self.library.tags("review-proposal", proposal_id=self.pending()[0]["id"], approve=True,
                          expected_hash=card["content_hash"])
        path = Path(card["path"])
        data = cards.read(path)
        data["metadata"]["tags"] = ["PY"]
        path.write_bytes(cards.render(data["metadata"], data["body"]))
        self.library.rebuild()
        record = self.library.tags("assignments")[0]
        self.assertTrue(record["locked_by_user"])
        self.assertEqual(record["origin"], "manual")

    def test_manual_message_and_conversation_assignments_filter_sources(self):
        self.python_tag()
        message = {"kind": "message", "conversation_id": "c1", "message_id": "m1"}
        self.library.tags("assign", slug="py", target=message)
        rows = self.library.search("ficticia", tag="programacion")
        self.assertEqual([r["message_id"] for r in rows], ["m1"])
        conversation_target = {"kind": "conversation", "conversation_id": "c1"}
        self.library.tags("assign", slug="py", target=conversation_target)
        self.assertEqual(len(self.library.search("ficticia", tag="PY")), 2)
        self.library.import_export(self.export)
        self.library.db.unlink()
        self.library.rebuild()
        self.assertEqual(len(self.library.search("ficticia", tag="py")), 2)
        self.assertTrue(all(a["locked_by_user"] for a in self.library.tags("assignments")))

    def test_card_assignment_requires_hash_and_stale_edits_keep_proposals(self):
        self.python_tag()
        card = self.card()
        target = {"kind": "card", "card_id": card["id"]}
        with self.assertRaises(LibraryError):
            self.library.tags("assign", slug="py", target=target)
        result = self.library.tags("assign", slug="py", target=target, expected_hash="old")
        self.assertTrue(result["conflict"])
        self.assertEqual(self.library.get_card(card["id"])["metadata"]["tags"], [])
        self.library.tags("assign", slug="py", target=target, expected_hash=card["content_hash"])
        current = self.library.get_card(card["id"])
        self.library.tags("assign", slug="py", target=target, expected_hash=current["content_hash"], remove=True)
        self.assertEqual(self.library.get_card(card["id"])["metadata"]["tags"], [])
        self.assertEqual(self.library.tags("assignments")[0]["state"], "blocked")

    def test_merge_preserves_human_markdown_aliases_and_assignments(self):
        self.python_tag()
        self.register("tecnologia")
        card = self.card(tags=["programacion/python"])
        before = Path(card["path"]).read_bytes()
        self.library.tags("merge", source="programacion", destination="tecnologia")
        self.assertEqual(self.library.search_cards(tag="tecnologia")[0]["id"], card["id"])
        self.library.tags("merge", source="programacion/python", destination="tecnologia")
        self.assertEqual(Catalog(self.library).require("py")["slug"], "tecnologia")
        self.assertEqual(len(self.library.search_cards(tag="py")), 1)
        self.assertEqual(len(self.library.tags("assignments")), 1)
        self.assertEqual(Path(card["path"]).read_bytes(), before)
        self.assertIn("programacion/python", self.library.tags("tree")[0]["aliases"])

    def test_merge_rejects_descendant_cycle_and_collapses_duplicate_assignments(self):
        self.python_tag()
        with self.assertRaises(LibraryError):
            self.library.tags("merge", source="programacion", destination="py")
        self.register("otro")
        card = self.card(tags=["programacion/python", "otro"])
        self.library.tags("merge", source="otro", destination="py")
        self.assertEqual(len(self.library.tags("assignments", target={"kind": "card", "card_id": card["id"]})), 1)
        self.assertTrue(self.library.tags("assignments")[0]["locked_by_user"])

    def test_sensitive_rules_require_opt_in_and_sensitivity_survives_merge(self):
        self.register("privado", sensitive=True)
        self.register("privado/tema")
        with self.assertRaises(LibraryError):
            self.rule("privado/tema")
        self.rule("privado/tema", allow_sensitive=True)
        self.register("general")
        self.rule("general")
        self.card()
        self.library.tags("merge", source="privado/tema", destination="general")
        self.assertTrue(Catalog(self.library).sensitive(Catalog(self.library).require("general")["id"]))
        counts = self.library.tags("classify")
        self.assertEqual(counts["sensitive_skipped"], 1)
        self.assertEqual(counts["new_proposals"], 1)

    def test_rules_are_literal_terms_with_word_boundaries(self):
        self.python_tag()
        self.card(body="cpython implementation")
        self.rule()
        self.assertEqual(self.library.tags("classify")["new_proposals"], 0)
        self.card(body="El término literal py.* está aquí.")
        self.library.tags("rule-add", slug="py", terms=["py.*"])
        self.assertEqual(self.library.tags("classify")["new_proposals"], 1)

    def test_marking_existing_tag_sensitive_invalidates_implicit_rule_proposals(self):
        tag = self.register("general")
        card = self.card()
        self.rule("general")
        self.library.tags("classify")
        proposal = self.pending()[0]
        marked = self.register("general", sensitive=True)
        self.assertEqual(marked["id"], tag["id"])
        self.assertTrue(marked["sensitive"])
        with self.assertRaises(LibraryError):
            self.library.tags("review-proposal", proposal_id=proposal["id"], approve=True, expected_hash=card["content_hash"])
        self.assertEqual(self.library.tags("classify")["outdated_proposals"], 1)
        self.assertEqual(self.pending(), [])
        self.rule("general", allow_sensitive=True)
        self.assertEqual(self.library.tags("classify")["new_proposals"], 1)

    def test_changed_evidence_and_deleted_rules_invalidate_proposals(self):
        self.python_tag()
        card = self.card()
        rule = self.rule()
        self.library.tags("classify")
        proposal = self.pending()[0]
        path = Path(card["path"])
        path.write_bytes(path.read_bytes() + b"\nChanged body.\n")
        with self.assertRaises(LibraryError):
            self.library.tags("review-proposal", proposal_id=proposal["id"], approve=True,
                              expected_hash=cards.read(path)["content_hash"])
        self.assertEqual(self.library.tags("classify")["new_proposals"], 1)
        self.assertEqual(len(self.library.tags("proposals", status="outdated")), 1)
        self.library.tags("rule-remove", rule_id=rule["id"])
        self.assertEqual(self.pending(), [])
        self.assertEqual(self.library.tags("rules"), [])

    def test_disappearing_keywords_and_deleted_cards_invalidate_pending_matches(self):
        self.python_tag()
        card = self.card()
        self.rule()
        self.library.tags("classify")
        path = Path(card["path"])
        data = cards.read(path)
        path.write_bytes(cards.render(data["metadata"], "No matching term."))
        counts = self.library.tags("classify")
        self.assertEqual(counts["outdated_proposals"], 1)
        self.assertEqual(self.pending(), [])
        path.write_bytes(cards.render(data["metadata"], "Python again."))
        self.library.tags("classify")
        path.unlink()
        self.assertEqual(self.library.tags("classify")["outdated_proposals"], 1)
        self.assertEqual(self.pending(), [])

    def test_rejecting_old_proposal_never_removes_a_new_manual_assignment(self):
        self.python_tag()
        card = self.card()
        self.rule()
        self.library.tags("classify")
        proposal = self.pending()[0]
        self.library.tags("assign", slug="py", target={"kind": "card", "card_id": card["id"]},
                          expected_hash=card["content_hash"])
        self.library.tags("review-proposal", proposal_id=proposal["id"], approve=False)
        self.assertEqual(self.library.get_card(card["id"])["metadata"]["tags"], ["programacion/python"])
        self.assertEqual(self.library.tags("assignments")[0]["state"], "assigned")

    def test_classify_message_rules_and_reimport_never_overwrites_manual_blocks(self):
        self.python_tag()
        self.rule(scope="messages")
        counts = self.library.tags("classify", scope="messages")
        self.assertEqual(counts["new_proposals"], 1)
        proposal = self.pending()[0]
        self.library.tags("review-proposal", proposal_id=proposal["id"], approve=False)
        self.export.write_bytes(encoded([conversation(text="Python versión nueva ficticia.")]))
        self.library.import_export(self.export)
        self.assertEqual(self.library.tags("classify", scope="messages")["new_proposals"], 0)
        self.assertEqual(self.library.search("python", tag="py"), [])

    def test_catalog_backup_restore_preserves_aliases_pending_and_rejections(self):
        self.python_tag()
        self.rule()
        first = self.card()
        second = self.card()
        self.library.tags("classify")
        proposals = self.pending()
        self.library.tags("review-proposal", proposal_id=proposals[0]["id"], approve=False)
        self.library.tags("assign", slug="py", target={"kind": "message", "conversation_id": "c1", "message_id": "m1"})
        archive = self.base / "catalog.zip"
        self.library.backup(archive)
        Library.restore(archive, self.base / "restored", self.base / "restored-vault")
        restored = Library(self.base / "restored")
        self.assertEqual(Catalog(restored).require("PY")["slug"], "programacion/python")
        self.assertEqual(len(restored.tags("proposals", status="pending")), 1)
        self.assertEqual(len(restored.tags("proposals", status="rejected")), 1)
        self.assertEqual(len(restored.search("python", tag="programacion")), 1)
        pending = restored.tags("proposals", status="pending")[0]
        card_id = pending["target"]["card_id"]
        restored.tags("review-proposal", proposal_id=pending["id"], approve=True,
                      expected_hash=restored.get_card(card_id)["content_hash"])
        self.assertEqual(len(restored.search_cards(tag="py")), 1)
        self.assertNotEqual(first["id"], second["id"])

    def test_migration_two_to_three_preserves_existing_cards(self):
        card = self.card()
        connection = self.library.connect()
        connection.executescript("DROP TABLE tag_assignments; DROP TABLE tags; PRAGMA user_version=2;")
        connection.close()
        self.library.rebuild()
        connection = self.library.connect()
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
        connection.close()
        self.assertEqual(self.library.get_card(card["id"])["id"], card["id"])

    def test_invalid_catalog_fails_without_leaking_contents(self):
        self.python_tag()
        catalog = Catalog(self.library)
        tag = catalog.require("py")
        catalog.data["tags"][tag["id"]]["parent_id"] = tag["id"]
        catalog.data["private_test"] = "SYNTHETIC_SECRET_NOT_FOR_LOGS"
        catalog.path.write_bytes(encoded(catalog.data))
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            self.assertEqual(main(["--instance", str(self.library.root), "tags", "tree"]), 2)
        self.assertNotIn("SYNTHETIC_SECRET_NOT_FOR_LOGS", output.getvalue())

    def test_cli_taxonomy_import_suggestions_and_log_privacy(self):
        output = io.StringIO()
        args = ["--instance", str(self.library.root)]
        with redirect_stdout(output), redirect_stderr(output):
            self.assertEqual(main(args + ["tags", "add", "programacion"]), 0)
            self.assertEqual(main(args + ["tags", "add", "programacion/python"]), 0)
            self.assertEqual(main(args + ["tags", "alias", "py", "programacion/python"]), 0)
            self.assertEqual(main(args + ["tags", "rule-add", "py", "--term", "python", "--scope", "messages"]), 0)
        output.seek(0)
        output.truncate()
        with redirect_stdout(output), redirect_stderr(output):
            self.assertEqual(main(args + ["import", str(self.export), "--suggest-tags"]), 0)
        self.assertNotIn("Python y biblioteca local ficticia.", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["tag_suggestions"]["new_proposals"], 1)
        proposal = self.pending()[0]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(args + ["tags", "accept", proposal["id"]]), 0)
            self.assertEqual(main(args + ["search", "python", "--tag", "py"]), 0)

    def test_windows_encoded_cli_preserves_multilingual_json(self):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="cp1252")
        try:
            with redirect_stdout(stream), redirect_stderr(io.StringIO()):
                code = main(["--instance", str(self.library.root), "tags", "add", "日本語", "--label", "日本語の資料"])
                stream.flush()
            self.assertEqual(code, 0)
            output = json.loads(buffer.getvalue().decode("utf-8"))
            self.assertEqual(output["slug"], "日本語")
            self.assertEqual(output["label"], "日本語の資料")
        finally:
            stream.detach()


if __name__ == "__main__":
    unittest.main()
