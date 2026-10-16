"""Independent instance, preserved sources, transcripts and rebuildable FTS5."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import uuid

from .parser import load_export, normalize
from .storage import LibraryError, atomic_write, confined, digest, encoded, exclusive, private_path


def now():
    return datetime.now(timezone.utc).isoformat()


def default_instance():
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "MAtlasAgent" / "default"


def anchor(message_id):
    return "msg-" + digest(message_id.encode())[:24]


def note_header(path):
    try:
        from .cards import MAX_HEADER, parse_header
        with path.open("rb") as stream:
            text = stream.read(MAX_HEADER + 1).decode("utf-8-sig", errors="replace")
        data, _ = parse_header(text)
        if isinstance(data, dict):
            return data
    except (UnicodeError, json.JSONDecodeError, LibraryError):
        pass
    return {}


def transcript(data):
    header = {"matlas_kind": "conversation", "source": "chatgpt", "conversation_id": data["id"],
              "created_at": data["created_at"], "updated_at": data["updated_at"]}
    # A JSON flow mapping is valid YAML; quote all untrusted metadata.
    lines = ["---", json.dumps(header, ensure_ascii=False), "---", "", "# " + data["title"].replace("\n", " "), ""]
    for message in data["messages"].values():
        lines.extend(["## " + message["role"].replace("\n", " "), "",
                      "Source ID: " + json.dumps(message["id"], ensure_ascii=False),
                      "Parent node: " + json.dumps(message["parent_id"], ensure_ascii=False), "",
                      message["text"], "", "^" + anchor(message["id"]), ""])
        if message["nontext"]:
            lines.extend(["> Non-text content is preserved in the original export; not rendered here.", ""])
    return "\n".join(lines).encode("utf-8")


class Library:
    def __init__(self, instance):
        self.root = private_path(Path(instance))
        config = confined(self.root, "instance.json")
        if not config.is_file():
            raise LibraryError("Instance not initialized. Run init first.")
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
            if data.get("schema_version") != 1:
                raise LibraryError("Unsupported instance schema.")
            self.vault = private_path(Path(data["vault"]))
            self.instance_id = data["instance_id"]
        except (KeyError, TypeError, json.JSONDecodeError):
            raise LibraryError("Invalid instance configuration.") from None
        if self.root == self.vault or self.root.is_relative_to(self.vault) or self.vault.is_relative_to(self.root):
            raise LibraryError("Vault and instance directories must be separate.")
        if not self.vault.is_dir():
            raise LibraryError("Configured vault is missing.")
        self.db = confined(self.root, "index.sqlite3")

    @classmethod
    def initialize(cls, instance, vault, *, allow_obsidian_config=False):
        root, vault = private_path(Path(instance)), private_path(Path(vault))
        if root == vault or root.is_relative_to(vault) or vault.is_relative_to(root):
            raise LibraryError("Vault and instance directories must be separate.")
        contents = list(vault.iterdir()) if vault.exists() else []
        if allow_obsidian_config:
            # A newly created Obsidian vault already contains its application config.
            # Never adopt notes or an existing managed library implicitly.
            has_config = any(p.name == ".obsidian" for p in contents)
            contents = [p for p in contents if p.name != ".obsidian"]
            if has_config:
                if not confined(vault, ".obsidian").is_dir():
                    raise LibraryError("Obsidian configuration must be a directory.")
        if (root.exists() and any(root.iterdir())) or contents:
            raise LibraryError("Init requires empty instance and vault directories.")
        root.mkdir(parents=True, exist_ok=True)
        vault.mkdir(parents=True, exist_ok=True)
        atomic_write(root / "instance.json", encoded({"schema_version": 1, "instance_id": str(uuid.uuid4()),
                                                     "vault": str(vault), "created_at": now()}))
        library = cls(root)
        library.rebuild()
        return library

    def connect(self):
        connection = sqlite3.connect(self.db)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > 3:
            connection.close()
            raise LibraryError("Index schema is newer than this application.")
        if version == 0:
            connection.executescript("""
                BEGIN;
                CREATE TABLE conversations(id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    created_at REAL, updated_at REAL, note_path TEXT, source_file TEXT NOT NULL);
                CREATE TABLE messages(conversation_id TEXT REFERENCES conversations(id),
                    id TEXT, node_id TEXT, parent_id TEXT, role TEXT, created_at REAL,
                    text TEXT, version INTEGER, PRIMARY KEY(conversation_id,id));
                CREATE TABLE message_versions(conversation_id TEXT, id TEXT, version INTEGER,
                    payload TEXT, PRIMARY KEY(conversation_id,id,version));
                CREATE VIRTUAL TABLE message_fts USING fts5(conversation_id UNINDEXED,
                    message_id UNINDEXED, text, tokenize='unicode61 remove_diacritics 2');
                CREATE TABLE import_batches(id TEXT PRIMARY KEY, file_hash TEXT, imported_at TEXT,
                    status TEXT, counts TEXT);
                CREATE INDEX message_dates ON messages(created_at);
                PRAGMA user_version=1;
                COMMIT;
            """)
            version = 1
        if version == 1:
            connection.executescript("""
                BEGIN;
                CREATE TABLE cards(id TEXT PRIMARY KEY, title TEXT, type TEXT, status TEXT,
                    created_at REAL, updated_at REAL, note_path TEXT UNIQUE, content_hash TEXT,
                    metadata TEXT, body TEXT);
                CREATE VIRTUAL TABLE card_fts USING fts5(card_id UNINDEXED,title,body,
                    tokenize='unicode61 remove_diacritics 2');
                CREATE INDEX card_filters ON cards(type,status,created_at);
                PRAGMA user_version=2;
                COMMIT;
            """)
            version = 2
        if version == 2:
            connection.executescript("""
                BEGIN;
                CREATE TABLE tags(id TEXT PRIMARY KEY, slug TEXT UNIQUE, label TEXT,
                    parent_id TEXT REFERENCES tags(id) DEFERRABLE INITIALLY DEFERRED,
                    status TEXT, sensitive INTEGER);
                CREATE TABLE tag_assignments(target_kind TEXT, target_key TEXT,
                    tag_id TEXT REFERENCES tags(id), origin TEXT, locked_by_user INTEGER,
                    PRIMARY KEY(target_kind,target_key,tag_id));
                CREATE INDEX assignment_filters ON tag_assignments(tag_id,target_kind,target_key);
                PRAGMA user_version=3;
                COMMIT;
            """)
        from .tags import target_key
        def sql_target(kind, entity_id, message_id):
            target = {"kind": kind, "card_id" if kind == "card" else "conversation_id": entity_id}
            if kind == "message":
                target["message_id"] = message_id
            return target_key(target)
        connection.create_function("matlas_target", 3, sql_target, deterministic=True)
        return connection

    def source_files(self):
        folder = confined(self.root, "sources")
        if not folder.exists():
            return []
        return [confined(self.root, str(p.relative_to(self.root))) for p in sorted(folder.glob("*.json"))]

    def note_locations(self):
        result = {}
        for directory, dirs, files in os.walk(self.vault, followlinks=False):
            for name in dirs:
                confined(self.vault, str((Path(directory) / name).relative_to(self.vault)))
            for name in files:
                if Path(name).suffix.lower() != ".md":
                    continue
                path = confined(self.vault, str((Path(directory) / name).relative_to(self.vault)))
                header = note_header(path)
                if header.get("matlas_kind") == "conversation" and isinstance(header.get("conversation_id"), str):
                    cid = header["conversation_id"]
                    if cid in result:
                        raise LibraryError("Duplicate conversation IDs in vault notes; resolve before importing.")
                    result[cid] = path
        return result

    @exclusive
    def import_export(self, path):
        raw, items = load_export(Path(path))
        file_hash = digest(raw)
        original = confined(self.root, "originals/" + file_hash + Path(path).suffix.lower())
        if not original.exists():
            atomic_write(original, raw)
        elif digest(original.read_bytes()) != file_hash:
            raise LibraryError("An archived original failed its integrity check.")
        counts = {"new_conversations": 0, "new_messages": 0, "updated_messages": 0,
                  "unchanged_messages": 0, "conflicts": 0, "missing_notes": 0,
                  "warnings": 0, "errors": 0}
        batch_id = str(uuid.uuid4())
        batch = {"id": batch_id, "file_hash": file_hash, "imported_at": now(),
                 "status": "running", "counts": counts}
        journal = confined(self.root, "imports/" + batch_id + ".json")
        atomic_write(journal, encoded(batch))
        locations = self.note_locations()
        seen = set()
        try:
            for item in items:
                try:
                    data, warnings = normalize(item)
                    if data["id"] in seen:
                        raise LibraryError("Duplicate conversation in input batch.")
                    seen.add(data["id"])
                except LibraryError:
                    counts["errors"] += 1
                    continue
                counts["warnings"] += warnings
                source = confined(self.root, "sources/" + digest(data["id"].encode()) + ".json")
                previous = json.loads(source.read_text(encoding="utf-8")) if source.exists() else None
                if previous and previous["data"]["id"] != data["id"]:
                    raise LibraryError("Source identity mismatch.")
                counts["new_conversations"] += int(previous is None)
                old_messages = previous["data"]["messages"] if previous else {}
                versions = previous["versions"] if previous else {}
                for mid, message in data["messages"].items():
                    if mid not in old_messages:
                        counts["new_messages"] += 1
                    elif message != old_messages[mid]:
                        counts["updated_messages"] += 1
                    else:
                        counts["unchanged_messages"] += 1
                    history = versions.setdefault(mid, [])
                    if not history or history[-1]["message"] != message:
                        history.append({"message": message, "observed_at": now(), "original_hash": file_hash})
                # A partial export never deletes previously archived messages or nodes.
                data["messages"] = {**old_messages, **data["messages"]}
                data["nodes"] = {**(previous["data"]["nodes"] if previous else {}), **data["nodes"]}
                rendered = transcript(data)
                generated_hash = previous.get("generated_hash") if previous else None
                note = locations.get(data["id"])
                if previous is None:
                    if note is None:
                        note = confined(self.vault, "Conversations/chat-" + digest(data["id"].encode()) + ".md")
                        if note.exists():
                            raise LibraryError("A new transcript path is already occupied.")
                        atomic_write(note, rendered)
                        generated_hash = digest(rendered)
                    elif digest(note.read_bytes()) == digest(rendered):
                        # Resume after interruption between note and source checkpoint.
                        generated_hash = digest(rendered)
                    else:
                        proposal = confined(self.root, "conflicts/" + digest(data["id"].encode()) + "-" + digest(rendered) + ".md")
                        atomic_write(proposal, rendered)
                        counts["conflicts"] += 1
                    locations[data["id"]] = note
                elif note is None:
                    counts["missing_notes"] += 1
                elif digest(note.read_bytes()) == generated_hash:
                    if digest(rendered) != generated_hash:
                        # Save a generated version before replacing an untouched transcript.
                        backup = confined(self.root, "transcript_versions/" + generated_hash + ".md")
                        if not backup.exists():
                            atomic_write(backup, note.read_bytes())
                        atomic_write(note, rendered)
                    generated_hash = digest(rendered)
                elif previous["data"] != data:
                    # Store proposal outside vault so it cannot become a duplicate canonical ID.
                    proposal = confined(self.root, "conflicts/" + digest(data["id"].encode()) + "-" + digest(rendered) + ".md")
                    if not proposal.exists():
                        atomic_write(proposal, rendered)
                    counts["conflicts"] += 1
                record = {"schema_version": 1, "data": data, "versions": versions,
                          "generated_hash": generated_hash, "original_hash": file_hash,
                          "note_path": str(note.relative_to(self.vault)) if note else None}
                # Per-conversation atomic checkpoint; retry recovers an interrupted index update.
                atomic_write(source, encoded(record))
            batch["status"] = "partial" if counts["errors"] else "completed"
        except BaseException:
            batch["status"] = "interrupted"
            raise
        finally:
            atomic_write(journal, encoded(batch))
        self.rebuild()
        return {"status": batch["status"], **counts}

    @exclusive
    def rebuild(self):
        locations = self.note_locations()
        connection = self.connect()
        try:
            with connection:
                for table in ("tag_assignments", "tags", "card_fts", "cards", "message_fts", "message_versions", "messages", "conversations", "import_batches"):
                    connection.execute("DELETE FROM " + table)
                for source in self.source_files():
                    record = json.loads(source.read_text(encoding="utf-8"))
                    data = record["data"]
                    note = locations.get(data["id"])
                    connection.execute("INSERT INTO conversations VALUES(?,?,?,?,?,?)", (
                        data["id"], data["title"], data["created_at"], data["updated_at"],
                        str(note) if note else None, str(source)))
                    for mid, message in data["messages"].items():
                        history = record["versions"][mid]
                        connection.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)", (
                            data["id"], mid, message["node_id"], message["parent_id"], message["role"],
                            message["created_at"], message["text"], len(history)))
                        connection.execute("INSERT INTO message_fts VALUES(?,?,?)", (data["id"], mid, message["text"]))
                        for version, payload in enumerate(history, 1):
                            connection.execute("INSERT INTO message_versions VALUES(?,?,?,?)", (
                                data["id"], mid, version, json.dumps(payload, ensure_ascii=False)))
                folder = confined(self.root, "imports")
                for p in sorted(folder.glob("*.json")):
                    p = confined(self.root, str(p.relative_to(self.root)))
                    batch = json.loads(p.read_text(encoding="utf-8"))
                    connection.execute("INSERT INTO import_batches VALUES(?,?,?,?,?)", (
                        batch["id"], batch["file_hash"], batch["imported_at"], batch["status"], json.dumps(batch["counts"])))
                from .cards import index_cards
                index_cards(self, connection)
                from .tags import index_catalog
                index_catalog(self, connection)
        finally:
            connection.close()
        return self.stats()

    def stats(self):
        connection = self.connect()
        try:
            return {table: connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
                    for table in ("conversations", "messages", "message_versions", "import_batches", "cards", "tags", "tag_assignments")}
        finally:
            connection.close()

    @exclusive
    def create_card(self, title, **kwargs):
        from .cards import create
        return create(self, title, **kwargs)

    @exclusive
    def update_card(self, card_id, **kwargs):
        from .cards import update
        return update(self, card_id, **kwargs)

    @exclusive
    def get_card(self, card_id):
        from .cards import find, reference_details, summary
        self.rebuild()
        card = find(self, card_id)
        return {**summary(card), "metadata": card["metadata"], "body": card["body"],
                "citations": [reference_details(self, r, include_text=True) for r in card["metadata"].get("sources", [])]}

    @exclusive
    def search_cards(self, query=None, *, kind=None, status=None, tag=None,
                     since=None, until=None, limit=20, offset=0):
        from .cards import TYPES, STATUSES, reference_details
        if not 1 <= limit <= 100 or offset < 0 or (query is not None and (not query.strip() or len(query) > 1000)):
            raise LibraryError("Invalid card search or pagination bounds.")
        if (kind is not None and kind not in TYPES) or (status is not None and status not in STATUSES):
            raise LibraryError("Invalid card search filter.")
        self.rebuild()  # Discover external edits, moves and deletions before returning results.
        clauses, parameters = [], []
        base = "FROM cards c"
        snippet = "''"
        if query is not None:
            base += " JOIN card_fts ON card_fts.card_id=c.id"
            clauses.append("card_fts MATCH ?")
            parameters.append(query)
            snippet = "snippet(card_fts,2,'[',']','…',24)"
        for expression, value in (("c.type=?", kind), ("c.status=?", status),
                                  ("c.created_at>=?", since), ("c.created_at<?", until)):
            if value is not None:
                clauses.append(expression)
                parameters.append(value)
        if tag is not None:
            from .tags import Catalog
            catalog = Catalog(self)
            try:
                ids = catalog.filter_ids(tag)
            except LibraryError:
                ids = []
            clauses.append("""(EXISTS(SELECT 1 FROM tag_assignments a WHERE a.target_kind='card'
                AND a.target_key=matlas_target('card',c.id,NULL)
                AND a.tag_id IN (SELECT value FROM json_each(?)))
                OR EXISTS(SELECT 1 FROM json_each(c.metadata,'$.tags') WHERE value=?))""")
            parameters.extend((json.dumps(ids), tag))
        sql = "SELECT c.id,c.title,c.type,c.status,c.note_path,c.content_hash,c.metadata," + snippet + " AS snippet " + base
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY c.created_at DESC,c.id LIMIT ? OFFSET ?"
        connection = self.connect()
        try:
            rows = [dict(row) for row in connection.execute(sql, (*parameters, limit, offset))]
            for row in rows:
                row["metadata"] = json.loads(row["metadata"])
                row["citations"] = [reference_details(self, r) for r in row["metadata"].get("sources", [])]
                row["note_uri"] = Path(row["note_path"]).as_uri()
            return rows
        except sqlite3.OperationalError:
            raise LibraryError("Invalid card search expression or unavailable index.") from None
        finally:
            connection.close()

    @exclusive
    def backup(self, path):
        from .recovery import backup
        return backup(self, Path(path))

    @classmethod
    def restore(cls, archive, instance, vault):
        from .recovery import restore
        return restore(Path(archive), Path(instance), Path(vault))

    @exclusive
    def list_conflicts(self):
        from .conflicts import list_conflicts
        return list_conflicts(self)

    @exclusive
    def resolve_conflict(self, name, *, action, expected_hash=None):
        from .conflicts import resolve
        return resolve(self, name, action=action, expected_hash=expected_hash)

    def search(self, query, *, role=None, since=None, until=None, tag=None, limit=20, offset=0):
        if not query.strip() or len(query) > 1000 or not 1 <= limit <= 100 or offset < 0:
            raise LibraryError("Invalid search query or pagination bounds.")
        clauses = ["message_fts MATCH ?"]
        params = [query]
        for expression, value in (("m.role = ?", role), ("m.created_at >= ?", since), ("m.created_at < ?", until)):
            if value is not None:
                clauses.append(expression)
                params.append(value)
        if tag is not None:
            self.rebuild()
            from .tags import Catalog
            ids = Catalog(self).filter_ids(tag)
            clauses.append("""EXISTS(SELECT 1 FROM tag_assignments a
                WHERE a.tag_id IN (SELECT value FROM json_each(?)) AND
                ((a.target_kind='message' AND a.target_key=matlas_target('message',m.conversation_id,m.id)) OR
                 (a.target_kind='conversation' AND a.target_key=matlas_target('conversation',m.conversation_id,NULL))))""")
            params.append(json.dumps(ids))
        sql = """SELECT c.title, c.id AS conversation_id, m.id AS message_id,
            m.role, m.created_at, m.version, c.note_path, c.source_file,
            snippet(message_fts,2,'[',']','…',24) AS snippet
            FROM message_fts JOIN messages m ON m.conversation_id=message_fts.conversation_id
            AND m.id=message_fts.message_id JOIN conversations c ON c.id=m.conversation_id
            WHERE """ + " AND ".join(clauses) + " ORDER BY m.created_at DESC,c.id,m.id LIMIT ? OFFSET ?"
        connection = self.connect()
        try:
            rows = [dict(row) for row in connection.execute(sql, (*params, limit, offset))]
            for row in rows:
                row["anchor"] = anchor(row["message_id"])
                row["note_uri"] = Path(row["note_path"]).as_uri() + "#" + row["anchor"] if row["note_path"] else None
                row["source"] = "chatgpt"
            return rows
        except sqlite3.OperationalError:
            raise LibraryError("Invalid FTS search expression or unavailable index.") from None
        finally:
            connection.close()

    @exclusive
    def tags(self, action, **kwargs):
        from .tags import Catalog, add_rule, assign, classify, review_proposal
        if action == "classify":
            return classify(self, **kwargs)
        if action == "assign":
            return assign(self, **kwargs)
        if action == "review-proposal":
            return review_proposal(self, **kwargs)
        self.rebuild()
        catalog = Catalog(self)
        if action == "register":
            result = catalog.register(**kwargs)
        elif action == "review":
            result = catalog.review(**kwargs)
        elif action == "alias":
            result = catalog.alias(**kwargs)
        elif action == "merge":
            result = catalog.merge(**kwargs)
        elif action == "rule-add":
            result = add_rule(catalog, **kwargs)
        elif action == "rule-remove":
            rule_id = kwargs["rule_id"]
            if rule_id not in catalog.data["rules"]:
                raise LibraryError("Rule not found.")
            del catalog.data["rules"][rule_id]
            for proposal in catalog.data["proposals"].values():
                if proposal["rule_id"] == rule_id and proposal["status"] == "pending":
                    proposal["status"] = "outdated"
            catalog.event("rule-remove", rule_id=rule_id)
            catalog.save()
            result = {"removed": rule_id}
        elif action == "tree":
            return catalog.tree()
        elif action in {"list", "rules", "proposals", "assignments", "audit"}:
            if action == "audit":
                return catalog.data["audit"][-min(1000, max(1, kwargs.get("limit", 100))):]
            values = list(catalog.data["tags" if action == "list" else action].values())
            if kwargs.get("status") is not None:
                values = [v for v in values if v.get("status") == kwargs["status"]]
            if kwargs.get("target") is not None:
                values = [v for v in values if v.get("target") == kwargs["target"]]
            return values
        else:
            raise LibraryError("Unknown tag operation.")
        self.rebuild()
        return result
