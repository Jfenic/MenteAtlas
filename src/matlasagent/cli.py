"""CLI output exposes contents only for explicit search; import logs are counts."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

from . import __version__
from .library import Library, default_instance
from .storage import LibraryError


def date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD (UTC).") from None


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
    commands.add_parser("stats", help="Show aggregate counts")
    commands.add_parser("rebuild-index", help="Rebuild SQLite from archived source records")
    search = commands.add_parser("search", help="Search source messages using SQLite FTS5")
    search.add_argument("query")
    search.add_argument("--role")
    search.add_argument("--from", dest="since", type=date)
    search.add_argument("--to", dest="until", type=date, help="Exclusive upper date bound (UTC)")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--offset", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            if not args.yes and input("Create local instance and vault? [y/N] ").strip().lower() not in {"y", "yes", "s", "si", "sí"}:
                return 0
            result = Library.initialize(args.instance, args.vault).stats()
        else:
            library = Library(args.instance)
            if args.command == "import":
                result = library.import_export(args.file)
            elif args.command == "stats":
                result = library.stats()
            elif args.command == "rebuild-index":
                result = library.rebuild()
            else:
                if args.since is not None and args.until is not None and args.since >= args.until:
                    raise LibraryError("The date range must increase.")
                result = library.search(args.query, role=args.role, since=args.since, until=args.until,
                                        limit=args.limit, offset=args.offset)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if isinstance(result, dict) and result.get("errors", 0) else 0
    except LibraryError as exc:
        print("MAtlasAgent: " + str(exc), file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, EOFError):
        print("MAtlasAgent: local operation failed; check file permissions and library integrity.", file=sys.stderr)
        return 2
