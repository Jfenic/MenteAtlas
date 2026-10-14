"""Canonical editable Markdown cards, strict bounded YAML and source citations."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import uuid

import yaml

from .storage import LibraryError, atomic_write, confined, digest, encoded

TYPES = ("idea", "decision", "information", "open_question")
STATUSES = ("draft", "reviewed", "archived")
MAX_CARD = 1024 * 1024
MAX_HEADER = 64 * 1024


class StrictLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise LibraryError("Card metadata has duplicate or non-string keys.")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def parse_header(text):
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None, text
    end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if end is None:
        raise LibraryError("Markdown front matter is incomplete.")
    header = "".join(lines[1:end])
    if len(header.encode("utf-8")) > MAX_HEADER:
        raise LibraryError("Card front matter exceeds 64 KiB.")
    try:
        tokens = list(yaml.scan(header))
        if any(isinstance(t, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken, yaml.tokens.TagToken)) for t in tokens):
            raise LibraryError("YAML aliases, anchors and explicit tags are not supported.")
        data = yaml.load(header, Loader=StrictLoader)
    except (yaml.YAMLError, RecursionError):
        raise LibraryError("Invalid YAML front matter.") from None
    if not isinstance(data, dict):
        raise LibraryError("Front matter must be a mapping.")
    return data, "".join(lines[end + 1:])


def valid_uuid(value):
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise LibraryError("Card IDs must be canonical UUID strings.") from None
    return value


def text_value(value, limit=4096, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not value.strip() and not empty):
        raise LibraryError("A card text field is invalid or too long.")
    if any(0xD800 <= ord(c) <= 0xDFFF or c == "\0" for c in value):
        raise LibraryError("A card text field contains invalid characters.")
    return value


def date_value(value):
    if isinstance(value, datetime):
        value = value.isoformat()
    try:
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None:
            raise ValueError()
        return timestamp.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        raise LibraryError("Card timestamps must include a timezone.") from None


def validate(metadata):
    if metadata.get("matlas_kind") != "card" or metadata.get("schema_version") != 1:
        raise LibraryError("Unsupported card schema.")
    valid_uuid(metadata.get("id"))
    text_value(metadata.get("title"))
    if metadata.get("type") not in TYPES or metadata.get("status") not in STATUSES:
        raise LibraryError("Invalid card type or review status.")
    for name in ("created_at", "updated_at"):
        metadata[name] = date_value(metadata.get(name))
    if metadata.get("origin") not in ("manual", "source_excerpt", "ai_proposal"):
        raise LibraryError("Invalid card origin.")
    if metadata.get("origin") == "ai_proposal" and not metadata.get("generated_by"):
        raise LibraryError("AI proposals must identify their generator.")
    if metadata.get("generated_by") is not None:
        text_value(metadata["generated_by"], 256)
    reviewer = metadata.get("reviewed_by")
    if metadata.get("status") == "reviewed" and not reviewer:
        raise LibraryError("Reviewed cards must identify their human reviewer.")
    if metadata.get("status") == "reviewed" and not metadata.get("reviewed_at"):
        raise LibraryError("Reviewed cards must record their human review timestamp.")
    if reviewer is not None:
        text_value(reviewer, 256)
    if metadata.get("reviewed_at") is not None:
        metadata["reviewed_at"] = date_value(metadata["reviewed_at"])
    tags = metadata.get("tags", [])
    sources = metadata.get("sources", [])
    if not isinstance(tags, list) or len(tags) > 200 or any(not isinstance(t, str) or not t or len(t) > 256 for t in tags):
        raise LibraryError("Invalid card tags.")
    for tag in tags:
        text_value(tag, 256)
    if not isinstance(sources, list) or len(sources) > 100:
        raise LibraryError("Cards support at most 100 source references.")
    keys = set()
    for reference in sources:
        if not isinstance(reference, dict) or reference.get("source") != "chatgpt":
            raise LibraryError("Invalid card source reference.")
        text_value(reference.get("conversation_id"), 512)
        text_value(reference.get("message_id"), 512)
        if type(reference.get("version")) is not int or reference["version"] < 1:
            raise LibraryError("Card references must identify a message version.")
        key = (reference["conversation_id"], reference["message_id"], reference["version"])
        if key in keys:
            raise LibraryError("Duplicate card source references.")
        keys.add(key)
    successor = metadata.get("superseded_by")
    if successor is not None:
        valid_uuid(successor)
        if metadata["type"] != "decision" or successor == metadata["id"]:
            raise LibraryError("Only decisions can reference another decision as successor.")
    # Metadata must remain portable JSON as well as safe YAML.
    try:
        json.dumps(metadata, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise LibraryError("Card metadata contains unsupported values.") from None
    return metadata


def render(metadata, body):
    validate(metadata)
    text_value(body, MAX_CARD, empty=True)
    output = ("---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False) + "---\n" + body).encode("utf-8")
    if len(output) > MAX_CARD:
        raise LibraryError("Card exceeds the 1 MiB limit.")
    return output


def read(path):
    if path.stat().st_size > MAX_CARD:
        raise LibraryError("Card exceeds the 1 MiB limit.")
    raw = path.read_bytes()
    try:
        metadata, body = parse_header(raw.decode("utf-8-sig"))
    except UnicodeError:
        raise LibraryError("Cards must be UTF-8 Markdown.") from None
    if metadata is None:
        raise LibraryError("Card front matter is missing.")
    validate(metadata)
    return {"metadata": metadata, "body": body, "content_hash": digest(raw), "path": path}


def scan(library):
    result = {}
    for directory, dirs, files in os.walk(library.vault, followlinks=False):
        for name in dirs:
            confined(library.vault, str((Path(directory) / name).relative_to(library.vault)))
        for name in files:
            if Path(name).suffix.lower() != ".md":
                continue
            path = confined(library.vault, str((Path(directory) / name).relative_to(library.vault)))
            # Probe only the bounded header, without loading unbounded ordinary notes.
            with path.open("rb") as stream:
                probe = stream.read(MAX_HEADER + 1)
            candidate = bool(re.search(rb"matlas_kind[\"']?\s*:\s*[\"']?card\b", probe))
            if not candidate and "Cards" not in path.relative_to(library.vault).parts[:-1]:
                continue
            card = read(path)
            cid = card["metadata"]["id"]
            if cid in result:
                raise LibraryError("Duplicate card IDs in vault; resolve before indexing.")
            result[cid] = card
    for cid, card in result.items():
        seen = {cid}
        successor = card["metadata"].get("superseded_by")
        while successor in result:
            if successor in seen:
                raise LibraryError("Decision succession contains a cycle.")
            if result[successor]["metadata"]["type"] != "decision":
                raise LibraryError("A decision successor must also be a decision.")
            seen.add(successor)
            successor = result[successor]["metadata"].get("superseded_by")
    return result


def find(library, card_id):
    valid_uuid(card_id)
    card = scan(library).get(card_id)
    if card is None:
        raise LibraryError("Card not found; deleted cards are not recreated automatically.")
    return card


def reference_details(library, reference, *, include_text=False):
    from .library import anchor
    connection = library.connect()
    try:
        row = connection.execute("""SELECT v.payload,c.note_path,c.source_file
            FROM message_versions v JOIN conversations c ON c.id=v.conversation_id
            WHERE v.conversation_id=? AND v.id=? AND v.version=?""", (
                reference["conversation_id"], reference["message_id"], reference["version"])).fetchone()
        if row is None:
            return {**reference, "available": False}
        payload = json.loads(row["payload"])
        message = payload["message"]
        result = {**reference, "available": True, "role": message["role"],
                  "created_at": message["created_at"], "original_hash": payload["original_hash"],
                  "source_file": row["source_file"], "source_pointer": message["source_pointer"],
                  "note_path": row["note_path"], "anchor": anchor(message["id"])}
        result["original_file"] = None
        for suffix in (".json", ".zip"):
            original = confined(library.root, "originals/" + payload["original_hash"] + suffix)
            if original.is_file():
                result["original_file"] = str(original)
                break
        if include_text:
            result["text"] = message["text"]
        return result
    finally:
        connection.close()


def resolve_references(library, sources):
    if not isinstance(sources, (list, tuple)) or len(sources) > 100:
        raise LibraryError("Cards support at most 100 source references.")
    references = []
    seen = set()
    connection = library.connect()
    try:
        for source in sources:
            if isinstance(source, (tuple, list)) and len(source) == 2:
                row = connection.execute("SELECT version FROM messages WHERE conversation_id=? AND id=?", source).fetchone()
                if row is None:
                    raise LibraryError("Selected source message is not archived.")
                source = {"source": "chatgpt", "conversation_id": source[0], "message_id": source[1], "version": row[0]}
            if not isinstance(source, dict) or not {"source", "conversation_id", "message_id", "version"} <= source.keys():
                raise LibraryError("Invalid source reference.")
            if source["source"] != "chatgpt" or type(source["version"]) is not int or source["version"] < 1:
                raise LibraryError("Invalid source reference version.")
            text_value(source["conversation_id"], 512)
            text_value(source["message_id"], 512)
            key = (source["conversation_id"], source["message_id"], source["version"])
            if key in seen:
                raise LibraryError("Duplicate card source references.")
            seen.add(key)
            if not reference_details(library, source)["available"]:
                raise LibraryError("Selected message version is not archived.")
            references.append(dict(source))
    finally:
        connection.close()
    return references


def summary(card):
    data = card["metadata"]
    return {"id": data["id"], "title": data["title"], "type": data["type"], "status": data["status"],
            "path": str(card["path"]), "content_hash": card["content_hash"], "sources": data.get("sources", [])}


def create(library, title, *, body="", kind="idea", sources=(), from_sources=False, tags=()):
    from .library import now
    library.rebuild()
    references = resolve_references(library, sources)
    if from_sources:
        if not references:
            raise LibraryError("Choose at least one source for an excerpt card.")
        for i, reference in enumerate(references, 1):
            source = reference_details(library, reference, include_text=True)
            if len(body) + len(source["text"]) > MAX_CARD:
                raise LibraryError("Source excerpts exceed the card size limit.")
            body += f"\n\n## Source {i} ({source['role']}, version {source['version']})\n\n"
            body += "\n".join("> " + line for line in source["text"].splitlines()) + "\n"
            if len(body) > MAX_CARD:
                raise LibraryError("Source excerpts exceed the card size limit.")
    timestamp = now()
    metadata = {"matlas_kind": "card", "schema_version": 1, "id": str(uuid.uuid4()),
                "title": title, "type": kind, "status": "draft", "created_at": timestamp,
                "updated_at": timestamp, "origin": "source_excerpt" if from_sources else "manual",
                "generated_by": None, "reviewed_by": None, "reviewed_at": None,
                "superseded_by": None, "tags": list(tags), "sources": references}
    path = confined(library.vault, "Cards/" + metadata["id"] + ".md")
    if path.exists():
        raise LibraryError("A card path is already occupied.")
    atomic_write(path, render(metadata, body))
    library.rebuild()
    return summary(read(path))


def update(library, card_id, *, expected_hash, body=None, title=None, kind=None,
           status=None, reviewer=None, sources=None, tags=None, superseded_by=None):
    from .library import now
    library.rebuild()
    card = find(library, card_id)
    metadata = dict(card["metadata"])
    for name, value in (("title", title), ("type", kind), ("status", status), ("tags", tags), ("superseded_by", superseded_by)):
        if value is not None:
            metadata[name] = value
    if sources is not None:
        metadata["sources"] = resolve_references(library, sources)
    metadata["updated_at"] = now()
    if status == "reviewed":
        if not reviewer:
            raise LibraryError("Provide the human reviewer when marking a card reviewed.")
        metadata["reviewed_by"], metadata["reviewed_at"] = reviewer, now()
    elif any(v is not None for v in (body, title, kind, sources, tags, superseded_by)) and card["metadata"]["status"] == "reviewed":
        # Editing a reviewed claim returns it to draft unless explicitly reviewed again.
        metadata["status"] = status or "draft"
        metadata["reviewed_by"], metadata["reviewed_at"] = None, None
    output = render(metadata, card["body"] if body is None else body)
    preview = {**card, "metadata": metadata, "body": card["body"] if body is None else body}
    all_cards = scan(library)
    all_cards[card_id] = preview
    successor = metadata.get("superseded_by")
    visited = {card_id}
    while successor is not None:
        if successor not in all_cards or successor in visited or all_cards[successor]["metadata"]["type"] != "decision":
            raise LibraryError("Invalid or cyclic decision successor.")
        visited.add(successor)
        successor = all_cards[successor]["metadata"].get("superseded_by")
    if digest(card["path"].read_bytes()) != expected_hash:
        proposal = confined(library.root, "conflicts/card-" + card_id + "-" + str(uuid.uuid4()) + ".md")
        atomic_write(proposal, output)
        return {"id": card_id, "conflict": True, "proposal": proposal.name,
                "current_hash": digest(card["path"].read_bytes())}
    old = card["path"].read_bytes()
    # Preserve the previous human card before a requested replacement.
    atomic_write(confined(library.root, "card_versions/" + card_id + "-" + digest(old) + ".md"), old)
    # Recheck after writing history to detect an external editor's intervening save.
    if digest(card["path"].read_bytes()) != expected_hash:
        proposal = confined(library.root, "conflicts/card-" + card_id + "-" + str(uuid.uuid4()) + ".md")
        atomic_write(proposal, output)
        return {"id": card_id, "conflict": True, "proposal": proposal.name}
    atomic_write(card["path"], output)
    library.rebuild()
    return summary(read(card["path"]))


def index_cards(library, connection):
    for card in scan(library).values():
        metadata = card["metadata"]
        connection.execute("INSERT INTO cards VALUES(?,?,?,?,?,?,?,?,?,?)", (
            metadata["id"], metadata["title"], metadata["type"], metadata["status"],
            datetime.fromisoformat(metadata["created_at"]).timestamp(),
            datetime.fromisoformat(metadata["updated_at"]).timestamp(),
            str(card["path"]), card["content_hash"], json.dumps(metadata, ensure_ascii=False), card["body"]))
        connection.execute("INSERT INTO card_fts VALUES(?,?,?)", (metadata["id"], metadata["title"], card["body"]))
