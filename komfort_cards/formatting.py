"""Normalisation and display formatting for codes and prices (FR-2, FR-7)."""

from __future__ import annotations

import re
from typing import Any

_SPACES = re.compile(r"[\s   ]+")
_PRICE = re.compile(r"^(\d+)(?:[.,](\d{1,2}))?$")


def normalize_code(value: Any) -> str:
    """Code exactly as in the table: strings untouched (leading zeros, dashes), Excel floats without '.0'."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def normalize_price(value: Any) -> str:
    """Canonical price string: digits with an optional ',dd' part; spaces removed. Raises ValueError if not a price."""
    if value is None:
        raise ValueError("пустая цена")
    if isinstance(value, bool):
        raise ValueError(f"цена не число: {value!r}")
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not value.is_integer():
            return f"{value:.2f}".replace(".", ",")
        return str(int(value))
    text = _SPACES.sub("", str(value)).replace("₸", "").replace("тг", "").strip()
    if not text:
        raise ValueError("пустая цена")
    match = _PRICE.match(text)
    if not match:
        raise ValueError(f"цена не число: {value!r}")
    whole, frac = match.groups()
    whole = whole.lstrip("0") or "0"
    return f"{whole},{frac.ljust(2, '0')}" if frac else whole


def format_price(value: Any, *, space: str = " ") -> str:
    """'131500' -> '131 500'; '1234,5' -> '1 234,50'. `space` lets HTML use a no-break space."""
    canonical = normalize_price(value)
    whole, _, frac = canonical.partition(",")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    text = space.join(groups)
    return f"{text},{frac}" if frac else text
