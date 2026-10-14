"""Private loopback transport for a desktop plugin; no remote bind or request logs."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
from urllib.parse import urlsplit

from . import __version__
from .library import Library
from .storage import LibraryError

MAX_JSON = 2 * 1024 * 1024
MAX_UPLOAD = 64 * 1024 * 1024


def open_library(instance, vault, *, initialize=False):
    """Binding is checked before any rebuild/write in an existing instance."""
    if (Path(instance) / "instance.json").exists():
        library = Library(instance)
        if library.vault != Path(vault).expanduser().resolve():
            raise LibraryError("The configured library belongs to a different vault.")
        library.rebuild()
        return library
    if not initialize:
        raise LibraryError("Library not initialized. Enable creation for a new empty vault.")
    return Library.initialize(instance, vault, allow_obsidian_config=True)


class LocalServer(HTTPServer):
    # Deliberately synchronous: the Library object and its reentrant writer guard
    # must not be shared by concurrent request workers.
    def __init__(self, library, token):
        if not isinstance(token, str) or not 32 <= len(token) <= 256 or not token.isascii():
            raise LibraryError("Invalid local session credential.")
        self.library, self.token = library, token
        super().__init__(("127.0.0.1", 0), Handler)

    def handle_error(self, request, client_address):
        # Never print request bodies, paths, authorization or tracebacks.
        pass


class Handler(BaseHTTPRequestHandler):
    server_version = "MAtlasAgent"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *args):
        pass

    def reply(self, status, data):
        output = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(output)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(output)
        self.close_connection = True

    def send_error(self, code, message=None, explain=None):
        self.reply(code, {"error": "Unsupported local API request."})

    def authorized(self):
        host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get_all("Host") != [host] or self.headers.get("Origin"):
            self.reply(403, {"error": "Local request rejected."})
            return False
        auth = self.headers.get_all("Authorization") or []
        if len(auth) != 1 or not hmac.compare_digest(auth[0].encode(), ("Bearer " + self.server.token).encode()):
            self.reply(401, {"error": "Local session authorization required."})
            return False
        return True

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def read_body(self, maximum):
        lengths = self.headers.get_all("Content-Length") or []
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
            raise LibraryError("A single bounded Content-Length is required.")
        try:
            length = int(lengths[0])
        except ValueError:
            raise LibraryError("Invalid request length.") from None
        if not 0 < length <= maximum:
            raise LibraryError("Request exceeds the local API size limit.")
        body = self.rfile.read(length)
        if len(body) != length:
            raise LibraryError("Incomplete request body.")
        return body

    def dispatch(self):
        if not self.authorized():
            return
        try:
            body = None
            if self.command == "POST":
                # Consume a bounded authorized body before rejecting its route.
                # Closing with unread request data can reset the TCP reply on Windows.
                maximum = MAX_UPLOAD if self.path == "/import" else MAX_JSON
                body = self.read_body(maximum)
            parsed = urlsplit(self.path)
            if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
                raise LibraryError("Invalid local endpoint.")
            endpoint = parsed.path
            lib = self.server.library
            if self.command == "GET":
                if endpoint == "/health":
                    result = {"protocol": 1, "version": __version__, "instance_id": lib.instance_id, "vault": str(lib.vault)}
                elif endpoint == "/stats":
                    result = lib.stats()
                elif endpoint == "/tags":
                    result = lib.tags("list", status="approved")
                else:
                    self.reply(404, {"error": "Unknown endpoint."})
                    return
            elif endpoint == "/import":
                if self.headers.get("Content-Type") != "application/octet-stream":
                    raise LibraryError("Import requires a binary export.")
                suffix = self.headers.get("X-MAtlas-Format")
                if suffix not in {"json", "zip"}:
                    raise LibraryError("Choose a JSON or ZIP export.")
                with tempfile.TemporaryDirectory(prefix=".pending-api-import-", dir=lib.root) as folder:
                    source = Path(folder) / ("export." + suffix)
                    source.write_bytes(body)
                    result = lib.import_export(source)
            else:
                if self.headers.get("Content-Type") != "application/json":
                    raise LibraryError("JSON request required.")
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise LibraryError("Request must be a JSON object.")
                if endpoint == "/search":
                    scope = data.pop("scope", "messages")
                    allowed = {"query", "tag", "limit", "offset"}
                    if data.keys() - allowed or scope not in {"messages", "cards"}:
                        raise LibraryError("Invalid search options.")
                    query = data.pop("query", "")
                    result = lib.search_cards(query or None, **data) if scope == "cards" else lib.search(query, **data)
                    for row in result:
                        note = row.get("note_path")
                        row["vault_path"] = str(Path(note).relative_to(lib.vault)).replace("\\", "/") if note else None
                elif endpoint == "/cards":
                    if data.keys() - {"title", "body", "kind", "sources", "from_sources", "tags"}:
                        raise LibraryError("Invalid card options.")
                    result = lib.create_card(**data)
                    result["vault_path"] = str(Path(result["path"]).relative_to(lib.vault)).replace("\\", "/")
                elif endpoint == "/backup":
                    if set(data) != {"path"} or not isinstance(data["path"], str):
                        raise LibraryError("Choose a new backup path.")
                    result = lib.backup(Path(data["path"]))
                elif endpoint == "/shutdown":
                    self.reply(200, {"stopping": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                else:
                    self.reply(404, {"error": "Unknown endpoint."})
                    return
            self.reply(200, result)
        except (LibraryError, json.JSONDecodeError, UnicodeError, TypeError, ValueError, KeyError) as error:
            message = str(error) if isinstance(error, LibraryError) else "Invalid request data."
            self.reply(400, {"error": message})
        except Exception:
            self.reply(500, {"error": "Local operation failed. Check permissions, free space and library integrity."})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Protected MAtlasAgent Obsidian transport")
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--initialize", action="store_true")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        # Credential arrives via a private pipe, never command line/config/logs.
        config = json.loads(sys.stdin.buffer.readline(1024))
        token = config["token"]
        if not isinstance(token, str) or not 32 <= len(token) <= 256 or not token.isascii():
            raise LibraryError("Invalid local session credential.")
        library = open_library(args.instance, args.vault, initialize=args.initialize)
        with LocalServer(library, token) as server:
            print(json.dumps({"port": server.server_port, "protocol": 1, "vault": str(library.vault)}), flush=True)
            def parent_closed():
                # EOF or plugin unload stops the engine after any active operation.
                while sys.stdin.buffer.read(1):
                    pass
                server.shutdown()
            threading.Thread(target=parent_closed, daemon=True).start()
            server.serve_forever(poll_interval=.1)
        return 0
    except Exception:
        print("MAtlasAgent could not start. Check Python, instance and vault configuration.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
