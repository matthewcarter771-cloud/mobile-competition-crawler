from datetime import date, datetime, timezone

import pytest

from crawler.competitors.parsing import (
    parse_data,
    parse_promotion_code,
    parse_promotion_end,
)

OBSERVED_AT = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("value, expected", [
    ("120GB", 120.0),
    ("4GB", 4.0),
    ("1.5GB", 1.5),
    ("250 GB", 250.0),
    ("500MB", 0.5),
    ("Unlimited", None),
    ("", None),
])
def test_parse_data(value, expected):
    assert parse_data(value) == expected


@pytest.mark.parametrize("text, expected", [
    ("Get £2 off a month with code 2OFF", "2OFF"),
    ("Use code SAVE10 at checkout", "SAVE10"),
    # Real labels without a code
    ("Flash sale - ends 5 November", None),
    ("Includes £10 a month discount", None),
    ("Great value", None),
    # "code" followed by an ordinary lowercase word isn't a code
    ("No code needed", None),
    (None, None),
])
def test_parse_promotion_code(text, expected):
    assert parse_promotion_code(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Flash sale - ends 5 November", date(2026, 11, 5)),
    ("Great low price. Ends 4 November.", date(2026, 11, 4)),
    ("Offer ends 5th Nov", date(2026, 11, 5)),
    ("Ends 23 October", date(2026, 10, 23)),
    # A date earlier in the year than the observation is next year's
    ("Sale ends 2 January", date(2027, 1, 2)),
    ("Ends 1 March 2027", date(2027, 3, 1)),
    # No usable date
    ("Flash sale", None),
    ("6 months half price", None),
    ("Ends 31 February", None),
    ("Ends 5 Smarch", None),
    (None, None),
])
def test_parse_promotion_end(text, expected):
    assert parse_promotion_end(text, OBSERVED_AT) == expected
