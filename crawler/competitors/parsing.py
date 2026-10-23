"""Validation and parsing helpers shared by the competitor crawlers."""

import calendar
import json
import re
from datetime import date, datetime
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


# "jan" -> 1 ... "dec" -> 12; matched on the first three letters so both
# "Nov" and "November" work
MONTHS = {
    name[:3].lower(): number
    for number, name in enumerate(calendar.month_name) if name
}


def parse_promotion_code(text: str | None) -> str | None:
    """Find a discount code, e.g. "Get £2 off a month with code 2OFF"."""
    if not text:
        return None

    match = re.search(r"\bcode\s+([A-Z0-9]{3,20})\b", text)
    return match.group(1) if match else None


def parse_promotion_end(
    text: str | None,
    observed_at: datetime
) -> date | None:
    """Find an end date, e.g. "Flash sale - ends 5 November".

    Without a year, the date is the next 5 November on or after the day
    the offer was observed.
    """
    if not text:
        return None

    match = re.search(
        r"\bends?\s+(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\.?(?:\s+(\d{4}))?",
        text,
        re.IGNORECASE
    )
    if not match:
        return None

    month = MONTHS.get(match.group(2)[:3].lower())
    if month is None:
        return None

    day = int(match.group(1))
    observed_on = observed_at.date()

    try:
        if match.group(3):
            return date(int(match.group(3)), month, day)

        end = date(observed_on.year, month, day)
        if end < observed_on:
            end = date(observed_on.year + 1, month, day)
        return end
    except ValueError:
        # e.g. "ends 31 February"
        return None


def promotion_fields(text: str | None, observed_at: datetime) -> dict:
    return dict(
        promotion_text=text,
        promotion_code=parse_promotion_code(text),
        promotion_ends_on=parse_promotion_end(text, observed_at),
    )
