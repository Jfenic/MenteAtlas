"""Durable approved vocabulary, aliases and reviewed deterministic assignments."""
import json
from pathlib import Path
import re
import unicodedata
import uuid

from . import cards
from .library import now
from .storage import LibraryError, atomic_write, confined, digest, encoded

MAX_RECORDS = 100_000
MAX_CATALOG = 64 * 1024 * 1024


def normalize(value):
    cards.text_value(value, 256)
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    segments = [re.sub(r"\s+", "-", part.strip()) for part in value.split("/")]
    if len(segments) > 32 or any(not s or len(s) > 64 or not re.fullmatch(r"[\w-]+", s) for s in segments):
        raise LibraryError("Tag names need letters, numbers, underscores, hyphens and optional hierarchy slashes.")
    return "/".join(segments)


def target_key(target):
    return digest(encoded(target))


def assignment_key(target, tag_id):
    return digest(encoded({"target": target, "tag_id": tag_id}))


def validate_target(target):
    if not isinstance(target, dict) or target.get("kind") not in {"card", "message", "conversation"}:
        raise LibraryError("Invalid tag assignment target.")
    if target["kind"] == "card":
        cards.valid_uuid(target.get("card_id"))
        expected = {"kind", "card_id"}
    else:
        cards.text_value(target.get("conversation_id"), 512)
        expected = {"kind", "conversation_id"}
        if target["kind"] == "message":
            cards.text_value(target.get("message_id"), 512)
            expected.add("message_id")
    if set(target) != expected:
        raise LibraryError("Invalid target fields.")
    return target


class Catalog:
    def __init__(self, library):
        self.library = library
        self.path = confined(library.root, "tags.json")
        self.data = {"schema_version": 1, "tags": {}, "aliases": {}, "rules": {},
                     "assignments": {}, "proposals": {}, "card_state": {}, "audit": []}
        if self.path.exists():
            from .parser import unique
            if self.path.stat().st_size > MAX_CATALOG:
                raise LibraryError("Tag catalog exceeds the size limit.")
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"), object_pairs_hook=unique)
                self.validate()
            except (TypeError, KeyError, AttributeError, ValueError, RecursionError):
                raise LibraryError("Invalid tag catalog; restore its durable data from backup.") from None

    def resolve_id(self, tag_id):
        seen = set()
        while tag_id is not None:
            if tag_id in seen or tag_id not in self.data["tags"]:
                raise LibraryError("Invalid or cyclic tag redirect.")
            seen.add(tag_id)
            tag = self.data["tags"][tag_id]
            if tag["status"] != "merged":
                return tag_id
            tag_id = tag.get("merged_into")
        raise LibraryError("Merged tag has no canonical destination.")

    def lookup(self, value, *, approved=True):
        name = normalize(value)
        tag_id = self.data["aliases"].get(name)
        if tag_id is None:
            tag_id = next((t["id"] for t in self.data["tags"].values() if t["slug"] == name), None)
        if tag_id is None:
            return None
        tag = self.data["tags"][self.resolve_id(tag_id)]
        if approved and tag["status"] != "approved":
            return None
        return tag

    def require(self, value):
        tag = self.lookup(value)
        if tag is None:
            raise LibraryError("Choose an approved tag from tags tree.")
        return tag

    def sensitive(self, tag_id):
        seen = set()
        while tag_id is not None:
            tag_id = self.resolve_id(tag_id)
            if tag_id in seen:
                raise LibraryError("Cyclic tag hierarchy.")
            seen.add(tag_id)
            tag = self.data["tags"][tag_id]
            if tag.get("sensitive", False):
                return True
            tag_id = tag.get("parent_id")
        return False

    def validate(self):
        if self.data.get("schema_version") != 1:
            raise LibraryError("Unsupported catalog schema.")
        for key in ("tags", "aliases", "rules", "assignments", "proposals", "card_state"):
            if not isinstance(self.data.get(key), dict) or len(self.data[key]) > MAX_RECORDS:
                raise LibraryError("Invalid or oversized catalog section.")
        if not isinstance(self.data.get("audit"), list) or len(self.data["audit"]) > MAX_RECORDS:
            raise LibraryError("Invalid catalog audit.")
        slugs = set()
        for tag_id, tag in self.data["tags"].items():
            cards.valid_uuid(tag_id)
            if tag.get("id") != tag_id or normalize(tag["slug"]) != tag["slug"] or tag["slug"] in slugs:
                raise LibraryError("Tag IDs or canonical names collide.")
            slugs.add(tag["slug"])
            cards.text_value(tag["label"], 256)
            if tag["status"] not in {"approved", "proposed", "rejected", "merged"} or type(tag["sensitive"]) is not bool:
                raise LibraryError("Invalid tag status.")
            self.resolve_id(tag_id)
            if tag["status"] in {"approved", "proposed"}:
                visited = {tag_id}
                parent = tag.get("parent_id")
                while parent is not None:
                    parent = self.resolve_id(parent)
                    if parent in visited or self.data["tags"][parent]["status"] != "approved":
                        raise LibraryError("Invalid or cyclic tag hierarchy.")
                    visited.add(parent)
                    if len(visited) > 32:
                        raise LibraryError("Tag hierarchy exceeds 32 levels.")
                    parent = self.data["tags"][parent].get("parent_id")
        for alias, tag_id in self.data["aliases"].items():
            if normalize(alias) != alias:
                raise LibraryError("Alias is not normalized.")
            destination = self.resolve_id(tag_id)
            if self.data["tags"][destination]["status"] != "approved":
                raise LibraryError("Alias must point to an approved tag.")
            for tag in self.data["tags"].values():
                if tag["slug"] == alias and self.resolve_id(tag["id"]) != destination:
                    raise LibraryError("Alias collides with a canonical tag.")
        for rule_id, rule in self.data["rules"].items():
            cards.valid_uuid(rule_id)
            if rule.get("id") != rule_id:
                raise LibraryError("Rule identity mismatch.")
            if self.data["tags"][self.resolve_id(rule["tag_id"])]["status"] != "approved":
                raise LibraryError("Rules require approved tags.")
            if rule.get("scope") not in {"cards", "messages", "conversations", "all"} or type(rule.get("allow_sensitive")) is not bool:
                raise LibraryError("Invalid rule scope.")
            if not isinstance(rule.get("terms"), list) or not 1 <= len(rule["terms"]) <= 50:
                raise LibraryError("A rule requires 1–50 literal terms.")
            for term in rule["terms"]:
                cards.text_value(term, 256)
        for assignment in self.data["assignments"].values():
            validate_target(assignment["target"])
            self.resolve_id(assignment["tag_id"])
            if assignment["state"] not in {"assigned", "blocked"} or assignment["origin"] not in {"manual", "rule"}:
                raise LibraryError("Invalid tag assignment state.")
            if type(assignment.get("locked_by_user")) is not bool:
                raise LibraryError("Invalid assignment protection flag.")
        for proposal_id, proposal in self.data["proposals"].items():
            cards.valid_uuid(proposal_id)
            if proposal.get("id") != proposal_id or not re.fullmatch(r"[0-9a-f]{64}", proposal.get("observed_hash", "")):
                raise LibraryError("Invalid proposal identity or evidence hash.")
            validate_target(proposal["target"])
            self.resolve_id(proposal["tag_id"])
            if proposal["status"] not in {"pending", "approved", "rejected", "outdated"}:
                raise LibraryError("Invalid assignment proposal state.")
            if proposal["status"] == "pending" and proposal.get("rule_id") not in self.data["rules"]:
                raise LibraryError("Pending proposal references a missing rule.")
        for card_id, state in self.data["card_state"].items():
            cards.valid_uuid(card_id)
            if not isinstance(state, dict) or not isinstance(state.get("mapping"), dict):
                raise LibraryError("Invalid canonical card tag state.")
            for tag_id, values in state["mapping"].items():
                self.resolve_id(tag_id)
                if not isinstance(values, list) or len(values) > 200:
                    raise LibraryError("Invalid canonical card tag snapshot.")
                for value in values:
                    cards.text_value(value, 256)

    def event(self, action, **details):
        self.data["audit"].append({"at": now(), "action": action, **details})

    def save(self):
        self.validate()
        output = encoded(self.data)
        if len(output) > MAX_CATALOG:
            raise LibraryError("Tag catalog exceeds the size limit.")
        if not self.path.exists() or self.path.read_bytes() != output:
            atomic_write(self.path, output)

    def register(self, slug, *, label=None, proposed=False, sensitive=False):
        slug = normalize(slug)
        existing = self.lookup(slug, approved=False)
        if existing is not None:
            if sensitive and not existing["sensitive"]:
                existing.update(sensitive=True, updated_at=now())
                self.event("mark-sensitive", tag_id=existing["id"])
                self.save()
            return {**existing, "reused": True}
        parent_id = None
        if "/" in slug:
            parent_id = self.require(slug.rsplit("/", 1)[0])["id"]
        timestamp = now()
        tag = {"id": str(uuid.uuid4()), "slug": slug, "label": label or slug.rsplit("/", 1)[-1],
               "parent_id": parent_id, "status": "proposed" if proposed else "approved",
               "sensitive": bool(sensitive), "merged_into": None, "created_at": timestamp, "updated_at": timestamp}
        self.data["tags"][tag["id"]] = tag
        self.event("suggest" if proposed else "add", tag_id=tag["id"])
        self.save()
        return tag

    def review(self, value, *, approve):
        tag = self.lookup(value, approved=False)
        if tag is None or tag["status"] not in {"proposed", "rejected"}:
            raise LibraryError("Choose a proposed or rejected tag to review.")
        tag.update(status="approved" if approve else "rejected", updated_at=now())
        self.event("approve" if approve else "reject", tag_id=tag["id"])
        self.save()
        return tag

    def alias(self, alias, value):
        alias = normalize(alias)
        tag = self.require(value)
        existing = self.lookup(alias, approved=False)
        if existing is not None and existing["id"] != tag["id"]:
            raise LibraryError("Alias collides with another tag or synonym.")
        self.data["aliases"][alias] = tag["id"]
        self.event("alias", alias=alias, tag_id=tag["id"])
        self.save()
        return {"alias": alias, "tag_id": tag["id"], "slug": tag["slug"]}

    def canonical_assignments(self):
        result = {}
        for record in self.data["assignments"].values():
            record = {**record, "tag_id": self.resolve_id(record["tag_id"])}
            key = assignment_key(record["target"], record["tag_id"])
            current = result.get(key)
            if current is None or (record["locked_by_user"], record["state"] == "blocked") > (current["locked_by_user"], current["state"] == "blocked"):
                result[key] = record
        self.data["assignments"] = result
        return result

    def merge(self, source, destination):
        source, destination = self.require(source), self.require(destination)
        if source["id"] == destination["id"]:
            raise LibraryError("Choose two distinct canonical tags.")
        parent = destination["id"]
        while parent is not None:
            parent = self.resolve_id(parent)
            if parent == source["id"]:
                raise LibraryError("Cannot merge a tag into its own descendant.")
            parent = self.data["tags"][parent].get("parent_id")
        destination["sensitive"] = destination["sensitive"] or self.sensitive(source["id"])
        for tag in self.data["tags"].values():
            if tag.get("parent_id") == source["id"]:
                tag["parent_id"] = destination["id"]
        source.update(status="merged", merged_into=destination["id"], updated_at=now())
        self.canonical_assignments()
        self.event("merge", source_id=source["id"], destination_id=destination["id"])
        self.save()
        return {"merged": source["id"], "canonical": destination["id"], "slug": destination["slug"]}

    def tree(self):
        nodes = {t["id"]: {**t, "children": [], "aliases": []} for t in self.data["tags"].values() if t["status"] == "approved"}
        for alias, tag_id in self.data["aliases"].items():
            nodes[self.resolve_id(tag_id)]["aliases"].append(alias)
        for tag in self.data["tags"].values():
            if tag["status"] == "merged":
                node = nodes[self.resolve_id(tag["id"])]
                if tag["slug"] not in node["aliases"]:
                    node["aliases"].append(tag["slug"])
        roots = []
        for node in sorted(nodes.values(), key=lambda n: n["slug"]):
            parent = self.resolve_id(node["parent_id"]) if node["parent_id"] else None
            if parent:
                nodes[parent]["children"].append(node)
            else:
                roots.append(node)
        return roots

    def filter_ids(self, value):
        tag = self.lookup(value)
        if tag is None:
            return []
        ids = {tag["id"]}
        changed = True
        while changed:
            changed = False
            for candidate in self.data["tags"].values():
                parent = candidate.get("parent_id")
                if candidate["status"] == "approved" and parent and self.resolve_id(parent) in ids and candidate["id"] not in ids:
                    ids.add(candidate["id"])
                    changed = True
        return sorted(ids)

    def record_assignment(self, target, tag_id, *, remove=False, origin="manual", evidence=None):
        tag_id = self.resolve_id(tag_id)
        record = {"target": validate_target(target), "tag_id": tag_id, "state": "blocked" if remove else "assigned",
                  "origin": origin, "locked_by_user": origin == "manual", "updated_at": now(), "evidence": evidence}
        self.data["assignments"][assignment_key(target, tag_id)] = record
        return record

    def sync_cards(self, scanned):
        self.canonical_assignments()
        for card_id, card in scanned.items():
            target = {"kind": "card", "card_id": card_id}
            mapping = {}
            for value in card["metadata"].get("tags", []):
                try:
                    tag = self.lookup(value)
                except LibraryError:
                    tag = None  # Existing freeform metadata is kept verbatim, not silently cataloged.
                if tag:
                    mapping.setdefault(tag["id"], []).append(value)
            previous = {}
            for tag_id, values in self.data["card_state"].get(card_id, {}).get("mapping", {}).items():
                previous.setdefault(self.resolve_id(tag_id), []).extend(values)
            removed = previous.keys() - mapping.keys()
            removed |= {r["tag_id"] for r in self.data["assignments"].values()
                        if r["target"] == target and r["state"] == "assigned" and r["tag_id"] not in mapping}
            for tag_id in removed:
                self.record_assignment(target, tag_id, remove=True)
                self.event("card-manual-remove", card_id=card_id, tag_id=tag_id)
            for tag_id, values in mapping.items():
                key = assignment_key(target, tag_id)
                if (sorted(previous.get(tag_id, [])) != sorted(values) or key not in self.data["assignments"]
                        or self.data["assignments"][key]["state"] != "assigned"):
                    self.record_assignment(target, tag_id)
                    self.event("card-manual-assign", card_id=card_id, tag_id=tag_id)
            self.data["card_state"][card_id] = {"mapping": mapping}
        self.save()


def target_snapshot(library, target, *, with_text=False):
    validate_target(target)
    if target["kind"] == "card":
        card = cards.find(library, target["card_id"])
        return {"hash": card["content_hash"], "text": card["metadata"]["title"] + "\n" + card["body"] if with_text else ""}
    connection = library.connect()
    try:
        conversation = connection.execute("SELECT title FROM conversations WHERE id=?", (target["conversation_id"],)).fetchone()
        if conversation is None:
            raise LibraryError("Tag target conversation is not archived.")
        sql = "SELECT id,text,role,version FROM messages WHERE conversation_id=?"
        parameters = [target["conversation_id"]]
        if target["kind"] == "message":
            sql += " AND id=?"
            parameters.append(target["message_id"])
        rows = [dict(r) for r in connection.execute(sql + " ORDER BY id", parameters)]
        if target["kind"] == "message":
            rows = [r for r in rows if r["id"] == target["message_id"]]
            if not rows:
                raise LibraryError("Tag target message is not archived.")
            value = rows[0]
        else:
            value = {"title": conversation["title"], "messages": rows}
        text = "\n".join(r["text"] for r in rows)
        if target["kind"] == "conversation":
            text = conversation["title"] + "\n" + text
        return {"hash": digest(encoded(value)), "text": text if with_text else ""}
    finally:
        connection.close()


def assign(library, slug, target, *, remove=False, expected_hash=None, origin="manual", evidence=None):
    library.rebuild()
    catalog = Catalog(library)
    tag = catalog.require(slug)
    target_snapshot(library, target)
    if target["kind"] == "card":
        if not expected_hash:
            raise LibraryError("Card tag changes require the current --expect-hash.")
        card = cards.find(library, target["card_id"])
        values = []
        found = False
        for value in card["metadata"].get("tags", []):
            try:
                existing = catalog.lookup(value)
            except LibraryError:
                existing = None
            if existing and existing["id"] == tag["id"]:
                found = True
                if remove:
                    continue
            values.append(value)
        if not remove and not found:
            values.append(tag["slug"])
        result = library.update_card(target["card_id"], expected_hash=expected_hash, tags=values)
        if result.get("conflict"):
            return result
        catalog = Catalog(library)  # Respect canonical synchronization performed by update_card.
    record = catalog.record_assignment(target, tag["id"], remove=remove, origin=origin, evidence=evidence)
    catalog.event("remove" if remove else "assign", target=target, tag_id=tag["id"], origin=origin)
    catalog.save()
    library.rebuild()
    return record


def add_rule(catalog, slug, terms, *, scope="cards", allow_sensitive=False):
    tag = catalog.require(slug)
    if catalog.sensitive(tag["id"]) and not allow_sensitive:
        raise LibraryError("Sensitive tags require explicit --allow-sensitive on their rules.")
    normalized = sorted({re.sub(r"\s+", " ", unicodedata.normalize("NFKC", cards.text_value(t, 256)).casefold()).strip() for t in terms})
    for rule in catalog.data["rules"].values():
        if (catalog.resolve_id(rule["tag_id"]), rule["terms"], rule["scope"], rule["allow_sensitive"]) == (tag["id"], normalized, scope, allow_sensitive):
            return {**rule, "reused": True}
    rule = {"id": str(uuid.uuid4()), "tag_id": tag["id"], "terms": normalized, "scope": scope, "allow_sensitive": bool(allow_sensitive)}
    catalog.data["rules"][rule["id"]] = rule
    catalog.event("rule-add", rule_id=rule["id"], tag_id=tag["id"])
    catalog.save()
    return rule


def classify(library, *, scope="cards"):
    if scope not in {"cards", "messages", "conversations", "all"}:
        raise LibraryError("Invalid classification scope.")
    library.rebuild()
    catalog = Catalog(library)
    targets = []
    if scope in {"cards", "all"}:
        targets.extend({"kind": "card", "card_id": cid} for cid in cards.scan(library))
    connection = library.connect()
    try:
        if scope in {"conversations", "all"}:
            targets.extend({"kind": "conversation", "conversation_id": r[0]} for r in connection.execute("SELECT id FROM conversations"))
        if scope in {"messages", "all"}:
            targets.extend({"kind": "message", "conversation_id": r[0], "message_id": r[1]} for r in connection.execute("SELECT conversation_id,id FROM messages"))
    finally:
        connection.close()
    counts = {"new_proposals": 0, "existing_proposals": 0, "outdated_proposals": 0,
              "protected_assignments": 0, "sensitive_skipped": 0}
    live = {target_key(t) for t in targets}
    for proposal in catalog.data["proposals"].values():
        kind_scope = proposal["target"]["kind"] + "s"
        if (proposal["status"] == "pending" and scope in {"all", kind_scope}
                and target_key(proposal["target"]) not in live):
            proposal["status"] = "outdated"
            counts["outdated_proposals"] += 1
    for target in targets:
        snapshot = target_snapshot(library, target, with_text=True)
        for proposal in catalog.data["proposals"].values():
            if proposal["status"] == "pending" and proposal["target"] == target and proposal["observed_hash"] != snapshot["hash"]:
                proposal["status"] = "outdated"
                counts["outdated_proposals"] += 1
        text = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", snapshot["text"]).casefold())
        for rule in catalog.data["rules"].values():
            if rule["scope"] not in {"all", target["kind"] + "s"}:
                continue
            tag_id = catalog.resolve_id(rule["tag_id"])
            if catalog.sensitive(tag_id) and not rule["allow_sensitive"]:
                counts["sensitive_skipped"] += 1
                for proposal in catalog.data["proposals"].values():
                    if proposal["status"] == "pending" and proposal["target"] == target and proposal["rule_id"] == rule["id"]:
                        proposal["status"] = "outdated"
                        counts["outdated_proposals"] += 1
                continue
            terms = [t for t in rule["terms"] if re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", text)]
            if not terms:
                continue
            assigned = catalog.data["assignments"].get(assignment_key(target, tag_id))
            if assigned is not None:
                counts["protected_assignments"] += 1
                continue
            previous = [p for p in catalog.data["proposals"].values()
                        if p["target"] == target and catalog.resolve_id(p["tag_id"]) == tag_id and p["status"] == "pending"]
            if any(p["observed_hash"] == snapshot["hash"] for p in previous):
                counts["existing_proposals"] += 1
                continue
            for p in previous:
                p["status"] = "outdated"
            proposal = {"id": str(uuid.uuid4()), "target": target, "tag_id": tag_id, "rule_id": rule["id"],
                        "matched_terms": terms, "observed_hash": snapshot["hash"], "status": "pending", "created_at": now()}
            catalog.data["proposals"][proposal["id"]] = proposal
            counts["new_proposals"] += 1
    catalog.event("classify", scope=scope, counts=counts)
    catalog.save()
    return counts


def review_proposal(library, proposal_id, *, approve, expected_hash=None):
    library.rebuild()
    catalog = Catalog(library)
    proposal = catalog.data["proposals"].get(proposal_id)
    if proposal is None or proposal["status"] != "pending":
        raise LibraryError("Choose a pending assignment proposal.")
    tag = catalog.data["tags"][catalog.resolve_id(proposal["tag_id"])]
    if approve:
        rule = catalog.data["rules"].get(proposal["rule_id"])
        if rule is None or (catalog.sensitive(tag["id"]) and not rule["allow_sensitive"]):
            raise LibraryError("Sensitive proposal needs a current rule with explicit --allow-sensitive.")
        if target_snapshot(library, proposal["target"])["hash"] != proposal["observed_hash"]:
            raise LibraryError("Proposal evidence changed; classify again before approval.")
        existing = catalog.data["assignments"].get(assignment_key(proposal["target"], tag["id"]))
        if existing and existing["locked_by_user"]:
            raise LibraryError("A human assignment or rejection protects this target.")
        result = assign(library, tag["slug"], proposal["target"], expected_hash=expected_hash, origin="rule",
                        evidence={"rule_id": proposal["rule_id"], "matched_terms": proposal["matched_terms"],
                                  "observed_hash": proposal["observed_hash"]})
        if result.get("conflict"):
            return result
        catalog = Catalog(library)
    else:
        existing = catalog.data["assignments"].get(assignment_key(proposal["target"], tag["id"]))
        if existing is None or existing["state"] != "assigned":
            catalog.record_assignment(proposal["target"], tag["id"], remove=True)
    catalog.data["proposals"][proposal_id]["status"] = "approved" if approve else "rejected"
    catalog.event("proposal-approve" if approve else "proposal-reject", proposal_id=proposal_id)
    catalog.save()
    library.rebuild()
    return catalog.data["proposals"][proposal_id]


def index_catalog(library, connection):
    catalog = Catalog(library)
    catalog.sync_cards(cards.scan(library))
    for tag in catalog.data["tags"].values():
        connection.execute("INSERT INTO tags VALUES(?,?,?,?,?,?)", (
            tag["id"], tag["slug"], tag["label"], tag["parent_id"], tag["status"], int(tag["sensitive"])))
    for record in catalog.data["assignments"].values():
        if record["state"] == "assigned":
            connection.execute("INSERT INTO tag_assignments VALUES(?,?,?,?,?)", (
                record["target"]["kind"], target_key(record["target"]), catalog.resolve_id(record["tag_id"]),
                record["origin"], int(record["locked_by_user"])))
