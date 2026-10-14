"""Constrained paths and atomic, durable local writes."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from contextlib import contextmanager
from functools import wraps


class LibraryError(ValueError):
    """Public errors must not include conversation contents or personal paths."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def private_path(path: Path) -> Path:
    # Check both lexical ancestors and resolved ancestors, including Git worktrees.
    original = path.expanduser().absolute()
    resolved = original.resolve()
    for candidate in (original, resolved):
        if any((p / ".git").exists() for p in (candidate, *candidate.parents)):
            raise LibraryError("Instance paths must be outside Git repositories.")
    return resolved


def confined(root: Path, relative: str) -> Path:
    path = root / relative
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise LibraryError("A library path escapes its configured root.")
    # Reject even internal symlinks; do not treat links as user content.
    for p in (path, *path.parents):
        if p == root.parent:
            break
        if p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()):
            raise LibraryError("Linked directories are not supported inside libraries.")
    return path


@contextmanager
def write_lock(root):
    """OS-owned lock releases on crash; stale lock files do not block recovery."""
    path = confined(root, "writer.lock")
    with path.open("a+b") as stream:
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise LibraryError("Another process is writing this instance.") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def exclusive(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        if getattr(self, "_writing", False):
            return method(self, *args, **kwargs)
        with write_lock(self.root):
            self._writing = True
            try:
                return method(self, *args, **kwargs)
            finally:
                self._writing = False
    return wrapped
