"""Local state for one-shot frames.

The K622 can read its custom per-key frame back with the vendor mailbox
(``05 89 cc`` -> report 6), but older tool versions only had a local
write-ahead record. ``set`` still saves the exact frame it last wrote and uses
it as the base for the next call; ``set --from-device`` reads the device
frame directly. This module also stores timestamped config/palette backups.

Nothing here talks to the keyboard.
"""

import hashlib
import os
import tempfile
from typing import Optional

STATE_DIR_ENV = "K622RGB_STATE_DIR"
STATE_FILE_ENV = "K622RGB_STATE_FILE"
FRAME_FILENAME = "last-frame.bin"
_MAX_STATE_BYTES = 4096


class StateError(RuntimeError):
    """The local last-frame file could not be read or written."""


class BackupError(RuntimeError):
    """A config backup is missing, malformed, or does not match its manifest."""


class UnverifiedBackup(BackupError):
    """A legacy backup has no per-file hash manifest."""


def state_dir() -> str:
    """Directory for the last-frame file (``$XDG_STATE_HOME`` by default)."""
    override = os.environ.get(STATE_DIR_ENV)
    if override:
        return os.path.expanduser(override)
    base = os.environ.get("XDG_STATE_HOME")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(os.path.expanduser(base), "k622rgb")


def default_frame_path() -> str:
    override = os.environ.get(STATE_FILE_ENV)
    if override:
        return os.path.expanduser(override)
    return os.path.join(state_dir(), FRAME_FILENAME)


def load_frame(path: str) -> Optional[bytes]:
    """Return the saved frame, or ``None`` when it does not exist yet."""
    try:
        with open(path, "rb") as handle:
            data = handle.read(_MAX_STATE_BYTES + 1)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StateError(
            "cannot read the saved frame at %s: %s" % (path, exc.strerror or exc)
        ) from exc
    if len(data) > _MAX_STATE_BYTES:
        raise StateError(
            "the saved frame at %s is unexpectedly large (%d bytes); "
            "delete it or use --reset" % (path, len(data))
        )
    return data


def save_frame(path: str, data: bytes) -> None:
    """Atomically write ``data`` to ``path``."""
    parent = os.path.dirname(os.path.abspath(path))
    try:
        os.makedirs(parent, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="wb", dir=parent, prefix=".last-frame-", delete=False
        )
        try:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, path)
    except OSError as exc:
        raise StateError(
            "cannot save the frame to %s: %s" % (path, exc.strerror or exc)
        ) from exc


# --------------------------------------------------------------------------
# Device configuration backups
# --------------------------------------------------------------------------

import json
import time


def backup_dir() -> str:
    """Return a new timestamped backup directory under the state directory."""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    base = os.path.join(state_dir(), "backups")
    path = os.path.join(base, stamp)
    suffix = 1
    while os.path.exists(path):
        suffix += 1
        path = os.path.join(base, "%s-%d" % (stamp, suffix))
    return path


def files_manifest(files: dict) -> dict:
    """Return a deterministic manifest of sizes and SHA-256 hashes."""
    return {
        name: {
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        for name, data in sorted(files.items())
    }


def _valid_backup_filename(name) -> bool:
    return (
        isinstance(name, str)
        and bool(name)
        and name not in (".", "..")
        and not os.path.isabs(name)
        and "/" not in name
        and (os.path.altsep is None or os.path.altsep not in name)
    )


def _check_backup_filename(name) -> None:
    if not _valid_backup_filename(name):
        raise BackupError("invalid backup filename %r" % (name,))


def read_backup_dir(path: str) -> tuple[dict, dict]:
    """Read ``meta.json`` and every regular file in a backup directory.

    Returns ``(meta, files)`` where ``files`` maps ``{filename: bytes}``.
    ``meta.json`` must exist and contain a JSON object. Names are validated so
    a backup cannot escape its directory. A legacy ``meta.json`` without a
    ``files`` map is returned unchanged; use :func:`verify_backup_dir` when the
    hashes must be present.
    """
    meta_path = os.path.join(path, "meta.json")
    try:
        with open(meta_path, "r", encoding="utf-8") as handle:
            meta = json.load(handle)
    except FileNotFoundError as exc:
        raise BackupError("backup %s has no meta.json" % (path,)) from exc
    except (OSError, ValueError) as exc:
        raise BackupError(
            "cannot read backup metadata at %s: %s" % (meta_path, exc)
        ) from exc
    if not isinstance(meta, dict):
        raise BackupError(
            "malformed backup metadata at %s: expected a JSON object" % (meta_path,)
        )

    files = {}
    try:
        entries = sorted(os.scandir(path), key=lambda entry: entry.name)
    except OSError as exc:
        raise BackupError(
            "cannot read backup directory %s: %s" % (path, exc.strerror or exc)
        ) from exc
    for entry in entries:
        if entry.name == "meta.json" or not entry.is_file(follow_symlinks=False):
            continue
        _check_backup_filename(entry.name)
        try:
            with open(entry.path, "rb") as handle:
                files[entry.name] = handle.read()
        except OSError as exc:
            raise BackupError(
                "cannot read backup file %r: %s"
                % (entry.name, exc.strerror or exc)
            ) from exc
    return meta, files


def verify_backup_dir(
    path: str, required=(), descriptor_sha256: Optional[str] = None
) -> tuple[dict, dict]:
    """Validate a backup directory against its per-file manifest.

    Returns ``(meta, files)``. A legacy backup without a ``files`` map raises
    :class:`UnverifiedBackup`; all other problems raise :class:`BackupError`.
    If ``descriptor_sha256`` is given, the backup must have been made from that
    device descriptor.
    """
    meta, files = read_backup_dir(path)
    if "files" not in meta:
        raise UnverifiedBackup("unverified backup")
    manifest = meta["files"]
    if not isinstance(manifest, dict):
        raise BackupError(
            "malformed backup metadata at %s: 'files' must be an object" % (path,)
        )

    for name in required:
        _check_backup_filename(name)
        if name not in manifest:
            raise BackupError(
                "backup is missing required file %r in meta.json" % (name,)
            )

    for name, expected in manifest.items():
        _check_backup_filename(name)
        if (
            not isinstance(expected, dict)
            or "size" not in expected
            or "sha256" not in expected
        ):
            raise BackupError(
                "malformed manifest entry for %r in %s" % (name, path)
            )
        expected_size = expected["size"]
        expected_hash = expected["sha256"]
        if not isinstance(expected_size, int) or isinstance(expected_size, bool):
            raise BackupError(
                "malformed manifest entry for %r: invalid size %r"
                % (name, expected_size)
            )
        if not isinstance(expected_hash, str):
            raise BackupError(
                "malformed manifest entry for %r: invalid sha256 %r"
                % (name, expected_hash)
            )
        if name not in files:
            raise BackupError(
                "backup is missing file %r listed in meta.json" % (name,)
            )
        data = files[name]
        if len(data) != expected_size:
            raise BackupError(
                "size mismatch for %r: expected %d bytes, got %d"
                % (name, expected_size, len(data))
            )
        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != expected_hash.lower():
            raise BackupError(
                "sha256 mismatch for %r: expected %s, got %s"
                % (name, expected_hash, actual_hash)
            )

    if descriptor_sha256 is not None:
        actual_descriptor = meta.get("descriptor_sha256")
        if actual_descriptor != descriptor_sha256:
            raise BackupError(
                "descriptor sha256 mismatch for %s: expected %s, backup has %s"
                % (
                    path,
                    descriptor_sha256,
                    actual_descriptor if actual_descriptor is not None else "none",
                )
            )
    return meta, files


def write_backup_meta(path: str, meta: dict) -> str:
    """Atomically replace ``meta.json`` in an existing backup directory."""
    parent = os.path.abspath(path)
    target = os.path.join(parent, "meta.json")
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent,
            prefix=".meta-",
            delete=False,
        ) as handle:
            tmp_name = handle.name
            json.dump(meta, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except OSError as exc:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
        raise StateError(
            "cannot write backup metadata to %s: %s"
            % (target, exc.strerror or exc)
        ) from exc
    return target


def save_backup(files: dict, meta: dict) -> str:
    """Atomically write a set of named blobs plus ``meta.json``.

    Returns the backup directory.  The caller supplies ``files`` as
    ``{filename: bytes}``; names are validated so a backup cannot escape its
    directory.  ``meta.json`` always records a version-2 per-file manifest.
    """
    path = backup_dir()
    try:
        os.makedirs(path, exist_ok=False)
        for name, data in files.items():
            if not name or "/" in name or name in (".", ".."):
                raise StateError("invalid backup filename %r" % (name,))
            with open(os.path.join(path, name), "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        payload = dict(meta)
        payload["version"] = 2
        payload["files"] = files_manifest(files)
        payload.setdefault("created", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        with open(os.path.join(path, "meta.json"), "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise StateError(
            "cannot write backup to %s: %s" % (path, exc.strerror or exc)
        ) from exc
    return path
