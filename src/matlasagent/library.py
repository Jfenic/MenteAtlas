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
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) >= 3 and lines[0] == "---" and lines[2] == "---":
            data = json.loads(lines[1])
            if isinstance(data, dict):
                return data
    except (UnicodeError, json.JSONDecodeError):
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
    def initialize(cls, instance, vault):
        root, vault = private_path(Path(instance)), private_path(Path(vault))
        if root == vault or root.is_relative_to(vault) or vault.is_relative_to(root):
            raise LibraryError("Vault and instance directories must be separate.")
        if (root.exists() and any(root.iterdir())) or (vault.exists() and any(vault.iterdir())):
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
        if version > 1:
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
                if not name.endswith(".md"):
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
                for table in ("message_fts", "message_versions", "messages", "conversations", "import_batches"):
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
        finally:
            connection.close()
        return self.stats()

    def stats(self):
        connection = self.connect()
        try:
            return {table: connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
                    for table in ("conversations", "messages", "message_versions", "import_batches")}
        finally:
            connection.close()

    def search(self, query, *, role=None, since=None, until=None, limit=20, offset=0):
        if not query.strip() or len(query) > 1000 or not 1 <= limit <= 100 or offset < 0:
            raise LibraryError("Invalid search query or pagination bounds.")
        clauses = ["message_fts MATCH ?"]
        params = [query]
        for expression, value in (("m.role = ?", role), ("m.created_at >= ?", since), ("m.created_at < ?", until)):
            if value is not None:
                clauses.append(expression)
                params.append(value)
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
