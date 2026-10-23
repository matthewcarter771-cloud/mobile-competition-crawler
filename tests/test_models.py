from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from crawler.models import MobileOffer


def make_offer(monthly, listed, discount_months, term):
    return MobileOffer(
        observed_at=datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc),
        competitor="Test",
        source_url="https://example.com/sim",
        offer_type="SIM Only",
        monthly_price=Decimal(monthly) if monthly is not None else None,
        list_monthly_price=Decimal(listed) if listed is not None else None,
        discount_months=discount_months,
        contract_term_months=term,
    )


@pytest.mark.parametrize("monthly, listed, discount_months, term, total, average", [
    # £20 12 month plan, free for the first 6 months
    ("0", "20", 6, 12, "120", "10.00"),
    # No discount
    ("22", "22", None, 24, "528", "22.00"),
    # Whole-contract discount, e.g. Vodafone Unlimited Plus
    ("26", "43", 24, 24, "624", "26.00"),
    # Three 120GB Lite: 6 months half price
    ("8", "16", 6, 24, "336", "14.00"),
    # Three 120GB Value: 9 months half price; average rounds to the penny
    ("10.5", "21", 9, 24, "409.5", "17.06"),
    # One month rolling plan, first month half price
    ("18", "36", 1, 1, "18", "18.00"),
    # Rounds half up: 0.005 -> 0.01
    ("0.01", "0.02", 1, 2, "0.03", "0.02"),
])
def test_total_and_average(monthly, listed, discount_months, term, total, average):
    offer = make_offer(monthly, listed, discount_months, term)

    assert offer.total_contract_price == Decimal(total)
    assert offer.average_monthly_price == Decimal(average)


@pytest.mark.parametrize("monthly, listed, discount_months, term", [
    # Discounted, but for an unknown number of months
    ("8", "16", None, 24),
    # Missing inputs
    (None, "16", None, 24),
    ("16", None, None, 24),
    ("16", "16", None, None),
])
def test_total_unknown(monthly, listed, discount_months, term):
    offer = make_offer(monthly, listed, discount_months, term)

    assert offer.total_contract_price is None
    assert offer.average_monthly_price is None


@pytest.mark.parametrize("discount_months, term, message", [
    (13, 12, "discount_months 13 must be between 1 and contract_term_months 12"),
    (0, 12, "discount_months 0 must be between 1"),
    (None, 0, "contract_term_months must be at least 1"),
])
def test_invalid_term_or_discount_rejected(discount_months, term, message):
    with pytest.raises(ValidationError, match=message):
        make_offer("8", "16", discount_months, term)


def test_totals_are_serialised_for_bigquery():
    row = make_offer("0", "20", 6, 12).model_dump(mode="json")

    assert row["total_contract_price"] == "120"
    assert row["average_monthly_price"] == "10.00"
