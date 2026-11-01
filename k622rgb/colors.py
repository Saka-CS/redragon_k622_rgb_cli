"""Color parsing for the K622 CLI (standard library only)."""

import re
from typing import Tuple

Color = Tuple[int, int, int]

NAMED_COLORS = {
    "off": (0, 0, 0),
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "orange": (255, 165, 0),
    "purple": (128, 0, 128),
    "pink": (255, 192, 203),
    "warm": (255, 160, 60),
}

_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")


class ColorError(ValueError):
    """An unparseable or out-of-range color."""


def _channel(text: str) -> int:
    try:
        value = int(text, 10)
    except ValueError:
        raise ColorError("color channel %r is not a number" % text) from None
    if not 0 <= value <= 255:
        raise ColorError("color channel %d is outside 0..255" % value)
    return value


def parse_color(text: str) -> Color:
    """Parse ``#RRGGBB``, ``RRGGBB``, ``#RGB``, ``r,g,b``, or a color name."""
    if not isinstance(text, str):
        raise ColorError("color must be text, got %r" % (text,))
    value = text.strip()
    if not value:
        raise ColorError("empty color")

    named = NAMED_COLORS.get(value.lower())
    if named is not None:
        return named

    if "," in value:
        parts = [part.strip() for part in value.split(",")]
        if len(parts) != 3:
            raise ColorError(
                "expected three comma-separated channels, got %r" % text
            )
        return tuple(_channel(part) for part in parts)  # type: ignore[return-value]

    digits = value[1:] if value.startswith("#") else value
    if not _HEX_RE.match(digits):
        raise ColorError(
            "invalid color %r; use #RRGGBB, RRGGBB, r,g,b, or a color name" % text
        )
    if len(digits) == 3:
        digits = "".join(channel * 2 for channel in digits)
    if len(digits) != 6:
        raise ColorError(
            "invalid color %r; hex must be 3 or 6 digits" % text
        )
    return (
        int(digits[0:2], 16),
        int(digits[2:4], 16),
        int(digits[4:6], 16),
    )


def format_color(color: Color) -> str:
    """Return a lower-case ``#rrggbb`` string."""
    return "#%02x%02x%02x" % tuple(int(channel) for channel in color)
