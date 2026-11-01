"""Local state for one-shot frames.

The K622 can read its custom per-key frame back with the vendor mailbox
(``05 89 cc`` -> report 6), but older tool versions only had a local
write-ahead record. ``set`` still saves the exact frame it last wrote and uses
it as the base for the next call; ``set --from-device`` reads the device
frame directly. This module also stores timestamped config/palette backups.

Nothing here talks to the keyboard.
"""

import os
import tempfile
from typing import Optional

STATE_DIR_ENV = "K622RGB_STATE_DIR"
STATE_FILE_ENV = "K622RGB_STATE_FILE"
FRAME_FILENAME = "last-frame.bin"
_MAX_STATE_BYTES = 4096


class StateError(RuntimeError):
    """The local last-frame file could not be read or written."""


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


def save_backup(files: dict, meta: dict) -> str:
    """Atomically write a set of named blobs plus ``meta.json``.

    Returns the backup directory.  The caller supplies ``files`` as
    ``{filename: bytes}``; names are validated so a backup cannot escape its
    directory.
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
        payload.setdefault("version", 1)
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
