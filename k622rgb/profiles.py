"""Local lighting profiles for the Redragon K622.

A profile stores the exact 136-byte device config, the 441-byte effect
palette and (optionally) the 1024-byte custom per-key frame. Raw bytes are
hex-encoded so a profile is portable to another K622 running the same
firmware. Profiles are local files only; the keyboard's profile/keymap table
(`04 d8`) is never written.
"""

import json
import os
import tempfile
import time
from typing import Dict, List, Optional

PROFILE_ENV = "K622RGB_PROFILE_DIR"
PROFILE_VERSION = 1
CONFIG_HEX_LEN = 136 * 2
PALETTE_HEX_LEN = 441 * 2
FRAME_HEX_LEN = 1024 * 2


class ProfileError(RuntimeError):
    """A profile could not be read, written or validated."""


def profile_dir() -> str:
    override = os.environ.get(PROFILE_ENV)
    if override:
        return os.path.expanduser(override)
    base = os.environ.get("XDG_CONFIG_HOME")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(os.path.expanduser(base), "k622rgb", "profiles")


def _safe_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ProfileError("profile name must be non-empty")
    name = name.strip()
    if "/" in name or "\\" in name or name in (".", "..") or "\0" in name:
        raise ProfileError("profile name %r contains a path separator" % (name,))
    if len(name) > 80:
        raise ProfileError("profile name is too long (max 80 characters)")
    return name


def profile_path(name: str, directory: Optional[str] = None) -> str:
    return os.path.join(directory or profile_dir(), _safe_name(name) + ".json")


def _validate_blob(value, expected: int, label: str) -> bytes:
    if not isinstance(value, str):
        raise ProfileError("%s is not a hex string" % label)
    if len(value) != expected * 2:
        raise ProfileError(
            "%s is %d hex characters; expected %d"
            % (label, len(value), expected * 2)
        )
    try:
        return bytes.fromhex(value)
    except ValueError:
        raise ProfileError("%s is not valid hex" % label) from None


def save_profile(name: str, config: bytes, palette: bytes,
                 frame: Optional[bytes] = None,
                 directory: Optional[str] = None) -> str:
    name = _safe_name(name)
    if len(config) != 136:
        raise ProfileError("config must be 136 bytes")
    if len(palette) != 441:
        raise ProfileError("palette must be 441 bytes")
    if frame is not None and len(frame) != 1024:
        raise ProfileError("custom frame must be 1024 bytes")
    payload = {
        "version": PROFILE_VERSION,
        "name": name,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": bytes(config).hex(),
        "palette": bytes(palette).hex(),
    }
    if frame is not None:
        payload["custom_frame"] = bytes(frame).hex()

    path = profile_path(name, directory)
    parent = os.path.dirname(path)
    try:
        os.makedirs(parent, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=parent,
            prefix=".profile-", suffix=".json", delete=False,
        )
        try:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, path)
    except OSError as exc:
        raise ProfileError(
            "cannot save profile %s: %s" % (path, exc.strerror or exc)
        ) from exc
    return path


def load_profile(name: str, directory: Optional[str] = None) -> Dict:
    path = profile_path(name, directory)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        raise ProfileError("profile %r does not exist (%s)" % (name, path)) from None
    except OSError as exc:
        raise ProfileError(
            "cannot read profile %s: %s" % (path, exc.strerror or exc)
        ) from exc
    except ValueError as exc:
        raise ProfileError("profile %s is not valid JSON: %s" % (path, exc)) from exc
    if not isinstance(payload, dict):
        raise ProfileError("profile %s is not a JSON object" % path)
    if payload.get("version") != PROFILE_VERSION:
        raise ProfileError(
            "profile %s has version %r; expected %d"
            % (path, payload.get("version"), PROFILE_VERSION)
        )
    config = _validate_blob(payload.get("config"), 136, "config")
    palette = _validate_blob(payload.get("palette"), 441, "palette")
    frame = None
    if payload.get("custom_frame") is not None:
        frame = _validate_blob(payload.get("custom_frame"), 1024, "custom_frame")
    return {
        "name": payload.get("name", name),
        "path": path,
        "created": payload.get("created"),
        "config": config,
        "palette": palette,
        "custom_frame": frame,
    }


def list_profiles(directory: Optional[str] = None) -> List[Dict]:
    path = directory or profile_dir()
    try:
        names = sorted(
            entry[:-5]
            for entry in os.listdir(path)
            if entry.endswith(".json") and not entry.startswith(".")
        )
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise ProfileError(
            "cannot list %s: %s" % (path, exc.strerror or exc)
        ) from exc
    result = []
    for name in names:
        try:
            result.append(load_profile(name, directory))
        except ProfileError:
            result.append({"name": name, "path": profile_path(name, directory),
                           "error": "invalid profile"})
    return result


def delete_profile(name: str, directory: Optional[str] = None) -> str:
    path = profile_path(name, directory)
    try:
        os.unlink(path)
    except FileNotFoundError:
        raise ProfileError("profile %r does not exist (%s)" % (name, path)) from None
    except OSError as exc:
        raise ProfileError(
            "cannot delete profile %s: %s" % (path, exc.strerror or exc)
        ) from exc
    return path
