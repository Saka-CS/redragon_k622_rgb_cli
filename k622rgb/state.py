"""Local state for one-shot frames.

The K622 cannot read back its current LED buffer (feature report ``0x06`` GET
stalls without the official read handshake). To make successive ``set`` calls
additive, the tool saves the exact frame it last wrote and uses it as the base
for the next call. This is a record of what *we* sent, not a device read-back.

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
