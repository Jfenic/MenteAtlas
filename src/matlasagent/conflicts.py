"""Explicit proposal review; preserve current bytes before approved replacement."""
import json
from pathlib import Path
import uuid

from . import cards
from .library import note_header, now, transcript
from .storage import LibraryError, atomic_write, confined, digest, encoded


def proposal_path(library, name):
    if Path(name).name != name or not name.endswith(".md"):
        raise LibraryError("Choose a proposal filename from conflicts list.")
    path = confined(library.root, "conflicts/" + name)
    if not path.is_file():
        raise LibraryError("Conflict proposal not found.")
    return path


def audit_path(library, name):
    return confined(library.root, "conflict_resolutions/" + digest(name.encode()) + ".json")


def list_conflicts(library):
    result = []
    folder = confined(library.root, "conflicts")
    for path in sorted(folder.glob("*.md")):
        path = proposal_path(library, path.name)
        audit = audit_path(library, path.name)
        if audit.exists():
            resolved = json.loads(audit.read_text(encoding="utf-8"))
            if resolved.get("proposal_hash") == digest(path.read_bytes()):
                continue
        header = note_header(path)
        kind = header.get("matlas_kind")
        if kind not in {"card", "conversation"}:
            raise LibraryError("Conflict proposal metadata is invalid.")
        result.append({"proposal": path.name, "kind": kind,
                       "id": header.get("id") or header.get("conversation_id"),
                       "proposal_hash": digest(path.read_bytes())})
    return result


def resolve(library, name, *, action, expected_hash=None):
    if action not in {"keep", "apply"}:
        raise LibraryError("Conflict action must be keep or apply.")
    proposal = proposal_path(library, name)
    proposed = proposal.read_bytes()
    header = note_header(proposal)
    kind = header.get("matlas_kind")
    if action == "keep":
        if kind not in {"card", "conversation"}:
            raise LibraryError("Invalid conflict proposal.")
        atomic_write(audit_path(library, name), encoded({"proposal": name, "proposal_hash": digest(proposed),
                     "action": action, "resolved_at": now(), "target_hash_before": None}))
        library.rebuild()
        return {"resolved": True, "action": action, "proposal": name}
    target = None
    source_record = None
    if kind == "card":
        card = cards.read(proposal)
        target = cards.find(library, header["id"])["path"]
        # Applying a proposal must not introduce invalid decision relationships.
        all_cards = cards.scan(library)
        successor = card["metadata"].get("superseded_by")
        seen = {header["id"]}
        while successor is not None:
            if successor in seen or successor not in all_cards or all_cards[successor]["metadata"]["type"] != "decision":
                raise LibraryError("Proposal has an invalid decision successor.")
            seen.add(successor)
            successor = all_cards[successor]["metadata"].get("superseded_by")
        if action == "apply":
            cards.resolve_references(library, card["metadata"].get("sources", []))
    elif kind == "conversation":
        cid = header.get("conversation_id")
        target = library.note_locations().get(cid)
        source_record = confined(library.root, "sources/" + digest(cid.encode()) + ".json")
        record = json.loads(source_record.read_text(encoding="utf-8"))
        if action == "apply" and proposed != transcript(record["data"]):
            raise LibraryError("Transcript proposal is outdated; keep it or review a current proposal.")
    else:
        raise LibraryError("Invalid conflict proposal.")
    if action == "apply":
        if target is None or not expected_hash or digest(target.read_bytes()) != expected_hash:
            raise LibraryError("Current note changed or is missing; review it and provide its current hash.")
        current = target.read_bytes()
        history = confined(library.root, "resolved_versions/" + str(uuid.uuid4()) + ".md")
        atomic_write(history, current)
        if digest(target.read_bytes()) != expected_hash:
            raise LibraryError("Current note changed during resolution; retry after closing the editor.")
        atomic_write(target, proposed)
        if source_record is not None:
            record["generated_hash"] = digest(proposed)
            atomic_write(source_record, encoded(record))
    atomic_write(audit_path(library, name), encoded({"proposal": name, "proposal_hash": digest(proposed),
                 "action": action, "resolved_at": now(), "target_hash_before": expected_hash}))
    library.rebuild()
    return {"resolved": True, "action": action, "proposal": name}
