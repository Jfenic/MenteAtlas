"""Bounded parsing of user-selected ChatGPT exports; never extracts ZIP files."""
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

from .storage import LibraryError

MAX_EXPORT = 64 * 1024 * 1024
MAX_ZIP_TOTAL = 512 * 1024 * 1024
MAX_MEMBERS = 10_000
MAX_CONVERSATIONS = 10_000
MAX_NODES = 100_000


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LibraryError("Duplicate JSON keys are not supported.")
        result[key] = value
    return result


def load_export(path: Path):
    if path.suffix.lower() not in {".json", ".zip"}:
        raise LibraryError("Select a JSON or ZIP export.")
    if path.stat().st_size > MAX_EXPORT:
        raise LibraryError("Export exceeds the 64 MiB input limit.")
    raw = path.read_bytes()
    payload = raw
    if path.suffix.lower() == ".zip":
        import io
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                members = archive.infolist()
                if len(members) > MAX_MEMBERS or sum(m.file_size for m in members) > MAX_ZIP_TOTAL:
                    raise LibraryError("ZIP exceeds its size or member limit.")
                candidates = []
                for member in members:
                    name = member.filename.replace("\\", "/")
                    parts = PurePosixPath(name).parts
                    if (name.startswith("/") or ".." in parts or ":" in name
                            or stat.S_ISLNK(member.external_attr >> 16) or member.flag_bits & 1):
                        raise LibraryError("ZIP contains an unsafe or encrypted entry.")
                    if member.file_size / max(1, member.compress_size) > 200:
                        raise LibraryError("ZIP compression ratio exceeds the limit.")
                    if parts and parts[-1] == "conversations.json" and not member.is_dir():
                        candidates.append(member)
                if len(candidates) != 1:
                    raise LibraryError("ZIP must contain exactly one conversations.json.")
                if candidates[0].file_size > MAX_EXPORT:
                    raise LibraryError("Conversation JSON exceeds the size limit.")
                payload = archive.read(candidates[0])
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
            raise LibraryError("Invalid or unsupported ZIP export.") from None
    try:
        items = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(LibraryError("Invalid JSON number.")))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise LibraryError("Invalid UTF-8 JSON export.") from None
    if not isinstance(items, list) or len(items) > MAX_CONVERSATIONS:
        raise LibraryError("Export must be a bounded list of conversations.")
    return raw, items


def identifier(value):
    if not isinstance(value, str) or not value or len(value) > 512 or any(ord(c) < 32 for c in value):
        raise LibraryError("A source identifier is invalid.")
    return value


def timestamp(value):
    import math
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 253402300799:
        raise LibraryError("A source timestamp is invalid.")
    return value


def normalize(item):
    if not isinstance(item, dict):
        raise LibraryError("Invalid conversation record.")
    cid = identifier(item.get("id") or item.get("conversation_id"))
    title = item.get("title", "Untitled")
    mapping = item.get("mapping")
    if not isinstance(title, str) or len(title) > 4096 or not isinstance(mapping, dict) or len(mapping) > MAX_NODES:
        raise LibraryError("Invalid conversation title or message mapping.")
    messages = {}
    warnings = 0
    for node_id, node in mapping.items():
        identifier(node_id)
        if not isinstance(node, dict):
            raise LibraryError("Invalid message node.")
        parent = node.get("parent")
        if parent is not None:
            identifier(parent)
        message = node.get("message")
        if message is None:
            continue
        if not isinstance(message, dict):
            raise LibraryError("Invalid message record.")
        mid = identifier(message.get("id") or node_id)
        if mid in messages:
            raise LibraryError("Duplicate message identifiers in a conversation.")
        content = message.get("content")
        author = message.get("author")
        if not isinstance(content, dict) or not isinstance(author, dict):
            raise LibraryError("Invalid message content or author.")
        parts = content.get("parts", [])
        if not isinstance(parts, list):
            raise LibraryError("Invalid content parts.")
        role = author.get("role", "unknown")
        if not isinstance(role, str) or len(role) > 100:
            raise LibraryError("Invalid message role.")
        nontext = content.get("content_type") != "text" or any(not isinstance(p, str) for p in parts)
        warnings += int(nontext)
        messages[mid] = {"id": mid, "node_id": node_id, "parent_id": parent,
                         "role": role, "created_at": timestamp(message.get("create_time")),
                         "text": "\n".join(p for p in parts if isinstance(p, str)),
                         "nontext": nontext, "source_pointer": [cid, "mapping", node_id, "message"]}
    # All nodes, including empty root nodes, retain their branch relationships.
    nodes = {nid: {"parent": n.get("parent"), "children": n.get("children", [])} for nid, n in mapping.items()}
    for nid, node in nodes.items():
        children = node["children"]
        if not isinstance(children, list) or any(not isinstance(c, str) or c not in nodes for c in children):
            raise LibraryError("Invalid branch children.")
        if node["parent"] is not None and node["parent"] not in nodes:
            raise LibraryError("Missing branch parent.")
    visited = set()
    for nid in nodes:
        chain = set()
        current = nid
        while current is not None and current not in visited:
            if current in chain:
                raise LibraryError("Cyclic conversation branches.")
            chain.add(current)
            current = nodes[current]["parent"]
        visited.update(chain)
    return {"source": "chatgpt", "id": cid, "title": title,
            "created_at": timestamp(item.get("create_time")),
            "updated_at": timestamp(item.get("update_time")),
            "nodes": nodes, "messages": messages}, warnings
