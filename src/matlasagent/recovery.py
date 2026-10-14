"""Complete private backups, integrity-checked staging and non-overwriting restore."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import uuid
import zipfile

from . import __version__
from .storage import LibraryError, atomic_write, confined, encoded, private_path

MAX_FILES = 100_000
MAX_FILE = 1024 * 1024 * 1024
MAX_TOTAL = 8 * MAX_FILE
MAX_MANIFEST = 16 * 1024 * 1024
CHUNK = 1024 * 1024
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_name(name):
    if not isinstance(name, str) or not name or "\\" in name:
        raise LibraryError("Backup contains an unsafe filename.")
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or str(path) != name:
        raise LibraryError("Backup filenames must be normalized relative paths.")
    for part in path.parts:
        if (part in {".", "..", ".git"} or part.endswith((".", " "))
                or part.split(".")[0].upper() in RESERVED
                or any(c in '<>:"|?*' or ord(c) < 32 for c in part)):
            raise LibraryError("Backup contains an unsafe or non-portable filename.")
    return path


def signature(path):
    info = path.stat()
    return info.st_size, info.st_mtime_ns, info.st_ino


def inventory(root, prefix):
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            confined(root, str((Path(directory) / name).relative_to(root)))
        for name in files:
            relative = (Path(directory) / name).relative_to(root)
            path = confined(root, str(relative))
            if prefix == "instance" and (relative.as_posix() in {
                    "index.sqlite3", "index.sqlite3-wal", "index.sqlite3-shm", "index.sqlite3-journal", "writer.lock"}
                    or any(p.startswith(".pending-") for p in relative.parts)):
                continue
            if not path.is_file():
                raise LibraryError("Backup supports regular files only.")
            arcname = prefix + "/" + relative.as_posix()
            safe_name(arcname)
            result[arcname] = (path, signature(path))
    return result


def hash_stream(stream, output=None):
    hash_value = hashlib.sha256()
    total = 0
    while data := stream.read(CHUNK):
        total += len(data)
        if total > MAX_FILE:
            raise LibraryError("A backup file exceeds its size limit.")
        hash_value.update(data)
        if output is not None:
            output.write(data)
    return hash_value.hexdigest(), total


def assert_original(name, hash_value):
    parts = PurePosixPath(name).parts
    if len(parts) == 3 and parts[:2] == ("instance", "originals"):
        if Path(parts[2]).stem != hash_value:
            raise LibraryError("An archived original failed its integrity check.")


def backup(library, path):
    from .library import now
    destination = private_path(path)
    if destination.is_relative_to(library.root) or destination.is_relative_to(library.vault):
        raise LibraryError("Save backups outside the instance and vault.")
    if destination.exists():
        raise LibraryError("Backup destination already exists; choose a new filename.")
    library.rebuild()
    verify_sources(library)
    initial = {**inventory(library.root, "instance"), **inventory(library.vault, "vault")}
    if len(initial) > MAX_FILES or sum(s[0] for _, s in initial.values()) > MAX_TOTAL:
        raise LibraryError("Library exceeds backup size or file limits.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pending-backup-", dir=destination.parent)
    os.close(fd)
    try:
        entries = []
        # Stored ZIP entries avoid rejecting our own backups as compression bombs.
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, (source, before) in sorted(initial.items()):
                if before[0] > MAX_FILE:
                    raise LibraryError("A library file exceeds the backup size limit.")
                with source.open("rb") as stream, archive.open(name, "w", force_zip64=True) as output:
                    hash_value, size = hash_stream(stream, output)
                if signature(source) != before or size != before[0]:
                    raise LibraryError("A file changed during backup; retry after closing the editor.")
                assert_original(name, hash_value)
                entries.append({"path": name, "size": size, "sha256": hash_value})
            final = {**inventory(library.root, "instance"), **inventory(library.vault, "vault")}
            if initial != final:
                raise LibraryError("Library changed during backup; retry after closing the editor.")
            manifest = {"schema_version": 1, "application_version": __version__,
                        "instance_id": library.instance_id, "created_at": now(), "files": entries}
            manifest_bytes = encoded(manifest)
            if len(manifest_bytes) > MAX_MANIFEST:
                raise LibraryError("Backup manifest exceeds the size limit.")
            archive.writestr("manifest.json", manifest_bytes)
        with open(temporary, "r+b") as stream:
            os.fsync(stream.fileno())
        # Publish without replacing an existing destination, including one created mid-backup.
        os.link(temporary, destination)
        return {"files": len(entries), "bytes": sum(e["size"] for e in entries), "backup": str(destination)}
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_manifest(archive):
    infos = archive.infolist()
    if len(infos) > MAX_FILES + 1 or sum(i.file_size for i in infos) > MAX_TOTAL + MAX_MANIFEST:
        raise LibraryError("Backup archive exceeds its limits.")
    members, collision_keys = {}, set()
    for info in infos:
        safe_name(info.filename)
        # Case-insensitive duplicates collide on Windows even on a Linux reader.
        key = info.filename.casefold()
        if (info.is_dir() or key in collision_keys or stat.S_ISLNK(info.external_attr >> 16)
                or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                or info.flag_bits & 1 or info.file_size > MAX_FILE
                or info.file_size / max(1, info.compress_size) > 200):
            raise LibraryError("Backup has duplicate, linked, encrypted or oversized entries.")
        collision_keys.add(key)
        members[info.filename] = info
    info = members.get("manifest.json")
    if info is None or info.file_size > MAX_MANIFEST:
        raise LibraryError("Backup manifest is missing or oversized.")
    try:
        from .parser import unique
        manifest = json.loads(archive.read(info), object_pairs_hook=unique)
        if manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), list):
            raise LibraryError("Unsupported backup schema.")
        expected = {}
        for entry in manifest["files"]:
            name = entry["path"]
            parts = safe_name(name).parts
            if len(parts) < 2 or parts[0] not in {"instance", "vault"} or name in expected:
                raise LibraryError("Invalid backup manifest filename.")
            if (type(entry["size"]) is not int or not 0 <= entry["size"] <= MAX_FILE
                    or not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
                raise LibraryError("Invalid backup manifest checksum or size.")
            if name not in members or members[name].file_size != entry["size"]:
                raise LibraryError("Backup manifest and archive differ.")
            if name.startswith("instance/") and parts[1] in {
                    "index.sqlite3", "index.sqlite3-wal", "index.sqlite3-shm", "index.sqlite3-journal", "writer.lock"}:
                raise LibraryError("Backup must not contain a live index or writer lock.")
            expected[name] = entry
        if set(members) != {"manifest.json", *expected} or "instance/instance.json" not in expected:
            raise LibraryError("Backup has unlisted entries or missing configuration.")
        return manifest, expected
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise LibraryError("Invalid backup manifest.") from None


def empty_target(path):
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise LibraryError("Restore requires new or empty instance and vault directories.")


def clean_stage(path, parent):
    # Verify exact temporary-root scope before recursive cleanup on Windows.
    if path.exists():
        if path.resolve().parent != parent.resolve() or not path.name.startswith(".matlas-restore-"):
            raise LibraryError("Temporary restore cleanup path is invalid.")
        shutil.rmtree(path)


def publish_stage(stage, target):
    empty_target(target)
    if target.exists():
        target.rmdir()  # Non-recursive: cannot remove any concurrently added data.
    stage.rename(target)


def restore(path, instance, vault):
    from .library import Library, now
    root, vault = private_path(instance), private_path(vault)
    if root == vault or root.is_relative_to(vault) or vault.is_relative_to(root):
        raise LibraryError("Restore instance and vault must be separate.")
    empty_target(root)
    empty_target(vault)
    stages = []
    published = False
    try:
        with zipfile.ZipFile(path) as archive:
            manifest, entries = load_manifest(archive)
            for target in (root, vault):
                target.parent.mkdir(parents=True, exist_ok=True)
                stages.append(Path(tempfile.mkdtemp(prefix=".matlas-restore-", dir=target.parent)))
            staged_root, staged_vault = stages
            for name, entry in entries.items():
                parts = PurePosixPath(name).parts
                folder = staged_root if parts[0] == "instance" else staged_vault
                output = confined(folder, str(Path(*parts[1:])))
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as stream, output.open("xb") as target:
                    hash_value, size = hash_stream(stream, target)
                if size != entry["size"] or hash_value != entry["sha256"]:
                    raise LibraryError("Backup content failed its integrity check.")
                assert_original(name, hash_value)
            config = json.loads((staged_root / "instance.json").read_text(encoding="utf-8"))
            if config.get("schema_version") != 1 or config.get("instance_id") != manifest.get("instance_id"):
                raise LibraryError("Backup configuration identity or schema mismatch.")
            config.update({"vault": str(staged_vault), "instance_id": str(uuid.uuid4()),
                           "restored_from_instance_id": manifest["instance_id"], "restored_at": now()})
            atomic_write(staged_root / "instance.json", encoded(config))
            staged = Library(staged_root)
            verify_sources(staged)
            staged.rebuild()  # Validate all source records and canonical Markdown before publication.
            staged.db.unlink()
            (staged_root / "writer.lock").unlink(missing_ok=True)
            config["vault"] = str(vault)
            atomic_write(staged_root / "instance.json", encoded(config))
            publish_stage(staged_vault, vault)
            published = True
            publish_stage(staged_root, root)
        library = Library(root)
        stats = library.rebuild()  # Rebind all indexed paths to the final restored locations.
        return {"restored": True, "instance_id": library.instance_id, **stats}
    except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeError, KeyError, TypeError):
        if published:
            raise LibraryError("Restore publication failed; keep the target directories for recovery.") from None
        raise LibraryError("Invalid backup archive or archived data.") from None
    except OSError:
        if published:
            raise LibraryError("Restore publication failed; keep the target directories for recovery.") from None
        raise
    finally:
        for stage, parent in zip(stages, (root.parent, vault.parent)):
            clean_stage(stage, parent)


def verify_sources(library):
    """Every archived version must still have a preserved original export."""
    originals = confined(library.root, "originals")
    available = {p.stem for p in originals.glob("*") if p.is_file()}
    for path in library.source_files():
        record = json.loads(path.read_text(encoding="utf-8"))
        hashes = {record["original_hash"]}
        for versions in record["versions"].values():
            hashes.update(v["original_hash"] for v in versions)
        if not hashes <= available:
            raise LibraryError("An archived source version has no original export.")
