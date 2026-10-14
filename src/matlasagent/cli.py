"""CLI output exposes contents only for explicit search; import logs are counts."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

from . import __version__
from .library import Library, default_instance
from .cards import TYPES, STATUSES, MAX_CARD
from .storage import LibraryError


def date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD (UTC).") from None


def body_file(path):
    if path is None:
        return None
    if path.stat().st_size > MAX_CARD:
        raise LibraryError("Card body file exceeds 1 MiB.")
    return path.read_text(encoding="utf-8-sig")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="matlas", description="MAtlasAgent — your local knowledge atlas")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--instance", type=Path, default=default_instance(), help="Instance directory outside Git")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a separate empty instance and Obsidian vault")
    init.add_argument("--vault", type=Path, required=True)
    init.add_argument("--yes", action="store_true", help="Confirm creation without a prompt")
    importer = commands.add_parser("import", help="Import an explicitly selected JSON/ZIP export")
    importer.add_argument("file", type=Path)
    importer.add_argument("--suggest-tags", action="store_true", help="Generate reviewable matches from approved local rules")
    commands.add_parser("stats", help="Show aggregate counts")
    commands.add_parser("rebuild-index", help="Rebuild SQLite from archived source records")
    search = commands.add_parser("search", help="Search source messages using SQLite FTS5")
    search.add_argument("query")
    search.add_argument("--role")
    search.add_argument("--from", dest="since", type=date)
    search.add_argument("--to", dest="until", type=date, help="Exclusive upper date bound (UTC)")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--offset", type=int, default=0)
    search.add_argument("--scope", choices=("messages", "cards"), default="messages")
    search.add_argument("--type", dest="kind", choices=TYPES)
    search.add_argument("--status", choices=STATUSES)
    search.add_argument("--tag")
    card = commands.add_parser("card", help="Create, inspect and edit canonical knowledge cards")
    card_commands = card.add_subparsers(dest="card_command", required=True)
    create = card_commands.add_parser("create")
    create.add_argument("--title", required=True)
    create.add_argument("--type", dest="kind", choices=TYPES, default="idea")
    create.add_argument("--body-file", type=Path)
    create.add_argument("--source", nargs=2, action="append", default=[], metavar=("CONVERSATION_ID", "MESSAGE_ID"))
    create.add_argument("--from-sources", action="store_true")
    create.add_argument("--tag", action="append", default=[])
    show = card_commands.add_parser("show")
    show.add_argument("id")
    listing = card_commands.add_parser("list")
    listing.add_argument("--type", dest="kind", choices=TYPES)
    listing.add_argument("--status", choices=STATUSES)
    listing.add_argument("--tag")
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--offset", type=int, default=0)
    update = card_commands.add_parser("update")
    update.add_argument("id")
    update.add_argument("--expect-hash", required=True, help="Current content_hash from card show/list")
    update.add_argument("--title")
    update.add_argument("--type", dest="kind", choices=TYPES)
    update.add_argument("--status", choices=STATUSES)
    update.add_argument("--reviewer")
    update.add_argument("--body-file", type=Path)
    update.add_argument("--source", nargs=2, action="append", metavar=("CONVERSATION_ID", "MESSAGE_ID"))
    update.add_argument("--tag", action="append")
    update.add_argument("--superseded-by")
    backup = commands.add_parser("backup", help="Create a complete checksum-verified private backup")
    backup.add_argument("file", type=Path)
    restore = commands.add_parser("restore", help="Restore a backup into two empty directories")
    restore.add_argument("file", type=Path)
    restore.add_argument("--vault", type=Path, required=True)
    conflicts = commands.add_parser("conflicts", help="Review and explicitly resolve preserved proposals")
    conflict_commands = conflicts.add_subparsers(dest="conflict_command", required=True)
    conflict_commands.add_parser("list")
    conflict_show = conflict_commands.add_parser("show")
    conflict_show.add_argument("proposal")
    conflict_resolve = conflict_commands.add_parser("resolve")
    conflict_resolve.add_argument("proposal")
    action = conflict_resolve.add_mutually_exclusive_group(required=True)
    action.add_argument("--keep-current", action="store_true")
    action.add_argument("--apply", action="store_true")
    conflict_resolve.add_argument("--expect-hash")
    tags = commands.add_parser("tags", help="Approved vocabulary, aliases and reviewed assignment rules")
    tag_commands = tags.add_subparsers(dest="tag_command", required=True)
    for name in ("add", "suggest"):
        sub = tag_commands.add_parser(name)
        sub.add_argument("slug")
        sub.add_argument("--label")
        sub.add_argument("--sensitive", action="store_true")
    for name in ("approve", "reject"):
        tag_commands.add_parser(name).add_argument("slug")
    alias = tag_commands.add_parser("alias")
    alias.add_argument("synonym")
    alias.add_argument("slug")
    merge = tag_commands.add_parser("merge")
    merge.add_argument("source")
    merge.add_argument("destination")
    tag_commands.add_parser("tree")
    listing = tag_commands.add_parser("list")
    listing.add_argument("--status", choices=("approved", "proposed", "rejected", "merged"))
    rule = tag_commands.add_parser("rule-add")
    rule.add_argument("slug")
    rule.add_argument("--term", action="append", required=True)
    rule.add_argument("--scope", choices=("cards", "messages", "conversations", "all"), default="cards")
    rule.add_argument("--allow-sensitive", action="store_true")
    tag_commands.add_parser("rules")
    tag_commands.add_parser("rule-remove").add_argument("id")
    classifier = tag_commands.add_parser("classify")
    classifier.add_argument("--scope", choices=("cards", "messages", "conversations", "all"), default="cards")
    proposals = tag_commands.add_parser("proposals")
    proposals.add_argument("--status", choices=("pending", "approved", "rejected", "outdated"), default="pending")
    for name in ("accept", "reject-proposal"):
        review = tag_commands.add_parser(name)
        review.add_argument("id")
        review.add_argument("--expect-hash")
    for name in ("assign", "remove", "assignments"):
        sub = tag_commands.add_parser(name)
        if name != "assignments":
            sub.add_argument("slug")
            sub.add_argument("--expect-hash")
        targets = sub.add_mutually_exclusive_group(required=name != "assignments")
        targets.add_argument("--card")
        targets.add_argument("--conversation")
        sub.add_argument("--message")
    audit = tag_commands.add_parser("audit")
    audit.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            if not args.yes and input("Create local instance and vault? [y/N] ").strip().lower() not in {"y", "yes", "s", "si", "sí"}:
                return 0
            result = Library.initialize(args.instance, args.vault).stats()
        elif args.command == "restore":
            result = Library.restore(args.file, args.instance, args.vault)
        else:
            library = Library(args.instance)
            if args.command == "import":
                result = library.import_export(args.file)
                if args.suggest_tags:
                    result["tag_suggestions"] = library.tags("classify", scope="all")
            elif args.command == "stats":
                result = library.stats()
            elif args.command == "rebuild-index":
                result = library.rebuild()
            elif args.command == "backup":
                result = library.backup(args.file)
            elif args.command == "card":
                if args.card_command == "create":
                    result = library.create_card(args.title, kind=args.kind, body=body_file(args.body_file) or "",
                                                 sources=args.source, from_sources=args.from_sources, tags=args.tag)
                elif args.card_command == "show":
                    result = library.get_card(args.id)
                elif args.card_command == "list":
                    result = library.search_cards(kind=args.kind, status=args.status, tag=args.tag,
                                                  limit=args.limit, offset=args.offset)
                else:
                    result = library.update_card(args.id, expected_hash=args.expect_hash, title=args.title,
                                                 kind=args.kind, status=args.status, reviewer=args.reviewer,
                                                 body=body_file(args.body_file), sources=args.source, tags=args.tag,
                                                 superseded_by=args.superseded_by)
            elif args.command == "conflicts":
                if args.conflict_command == "list":
                    result = library.list_conflicts()
                elif args.conflict_command == "show":
                    from .conflicts import proposal_path
                    result = {"proposal": args.proposal,
                              "markdown": proposal_path(library, args.proposal).read_text(encoding="utf-8")}
                else:
                    result = library.resolve_conflict(args.proposal, action="keep" if args.keep_current else "apply",
                                                      expected_hash=args.expect_hash)
            elif args.command == "tags":
                action = args.tag_command
                if action in {"add", "suggest"}:
                    result = library.tags("register", slug=args.slug, label=args.label,
                                          proposed=action == "suggest", sensitive=args.sensitive)
                elif action in {"approve", "reject"}:
                    result = library.tags("review", value=args.slug, approve=action == "approve")
                elif action == "alias":
                    result = library.tags("alias", alias=args.synonym, value=args.slug)
                elif action == "merge":
                    result = library.tags("merge", source=args.source, destination=args.destination)
                elif action == "rule-add":
                    result = library.tags("rule-add", slug=args.slug, terms=args.term,
                                          scope=args.scope, allow_sensitive=args.allow_sensitive)
                elif action == "rule-remove":
                    result = library.tags(action, rule_id=args.id)
                elif action in {"accept", "reject-proposal"}:
                    result = library.tags("review-proposal", proposal_id=args.id, approve=action == "accept",
                                          expected_hash=args.expect_hash)
                elif action in {"assign", "remove", "assignments"}:
                    if args.message and not args.conversation:
                        raise LibraryError("Message assignments require --conversation.")
                    target = None
                    if args.card:
                        target = {"kind": "card", "card_id": args.card}
                    elif args.conversation:
                        target = {"kind": "message" if args.message else "conversation", "conversation_id": args.conversation}
                        if args.message:
                            target["message_id"] = args.message
                    if action == "assignments":
                        result = library.tags(action, target=target)
                    else:
                        result = library.tags("assign", slug=args.slug, target=target, remove=action == "remove",
                                              expected_hash=args.expect_hash)
                elif action == "classify":
                    result = library.tags(action, scope=args.scope)
                elif action in {"list", "proposals"}:
                    result = library.tags(action, status=args.status)
                elif action == "audit":
                    result = library.tags(action, limit=args.limit)
                else:
                    result = library.tags(action)
            elif args.command == "search":
                if args.since is not None and args.until is not None and args.since >= args.until:
                    raise LibraryError("The date range must increase.")
                if args.scope == "cards":
                    if args.role is not None:
                        raise LibraryError("Role filters apply to message searches only.")
                    result = library.search_cards(args.query, kind=args.kind, status=args.status, tag=args.tag,
                                                  since=args.since, until=args.until, limit=args.limit, offset=args.offset)
                else:
                    if any(value is not None for value in (args.kind, args.status)):
                        raise LibraryError("Type and status filters currently apply to card searches only.")
                    result = library.search(args.query, role=args.role, since=args.since, until=args.until,
                                            tag=args.tag, limit=args.limit, offset=args.offset)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if isinstance(result, dict) and (result.get("errors", 0) or result.get("conflict")) else 0
    except LibraryError as exc:
        print("MAtlasAgent: " + str(exc), file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, EOFError):
        print("MAtlasAgent: local operation failed; check file permissions and library integrity.", file=sys.stderr)
        return 2
