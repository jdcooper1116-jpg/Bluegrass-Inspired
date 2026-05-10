"""Pure classification utilities for combinations and pairs.

No I/O. All functions are stateless and accept raw string values.
"""

from __future__ import annotations


def classify_digit_pattern(value: str) -> str:
    """Return 'single', 'double', 'triple', or 'unknown' for a 3-digit string."""
    digits = str(value).strip()
    if not digits or not digits.isdigit() or len(digits) != 3:
        return "unknown"
    unique = len(set(digits))
    if unique == 3:
        return "single"
    if unique == 2:
        return "double"
    return "triple"


def classify_play_type(subtype: str | None) -> str:
    """Return 'straight', 'box', or 'unknown' from a subtype string."""
    if not subtype:
        return "unknown"
    low = subtype.lower()
    if "straight" in low:
        return "straight"
    if "box" in low:
        return "box"
    return "unknown"


def classify_pair(subtype: str | None) -> dict[str, str]:
    """Return {'position': ..., 'play_type': ...} from a pair subtype string."""
    if not subtype:
        return {"position": "unknown", "play_type": "unknown"}
    low = subtype.lower()
    if "front" in low:
        position = "front"
    elif "back" in low:
        position = "back"
    elif "split" in low:
        position = "split"
    else:
        position = "unknown"
    return {"position": position, "play_type": classify_play_type(subtype)}
