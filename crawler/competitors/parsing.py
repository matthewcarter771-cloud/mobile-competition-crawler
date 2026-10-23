"""Validation and parsing helpers shared by the competitor crawlers."""

import json
import re
from decimal import Decimal

from crawler.competitors.base import OfferParseError


def require(obj: dict, key: str, expected, context: str, path: str):
    """Return obj[key] if it has the expected type, else raise.

    context names the record in the error, e.g. "Three offering 123".
    """
    value = obj.get(key) if isinstance(obj, dict) else None

    # bool is a subclass of int, so reject it explicitly for numeric fields
    if isinstance(value, bool) or not isinstance(value, expected):
        raise OfferParseError(
            f"{context}: expected {path} to be "
            f"{type_names(expected)}, got {json.dumps(value)[:100]}"
        )

    return value


def type_names(expected) -> str:
    types = expected if isinstance(expected, tuple) else (expected,)
    return " or ".join(t.__name__ for t in types)


def to_decimal(value: float | None) -> Decimal | None:
    # Go via str so 10.5 becomes Decimal("10.5"), not a float approximation
    return Decimal(str(value)) if value is not None else None


def parse_data(value: str) -> float | None:
    """Parse "120GB" or "500MB" into GB. Returns None if there's no amount."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*(gb|mb)\b", value.lower())
    if not match:
        return None

    amount = float(match.group(1))
    return amount / 1000 if match.group(2) == "mb" else amount
