import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from crawler.competitors.base import OfferParseError
from crawler.reparse import reparse_row
from crawler.registry import CRAWLERS

FIXTURES = Path(__file__).parent / "fixtures"
OBSERVED_AT = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def three_records():
    return json.loads((FIXTURES / "three_offerings.json").read_text())


def vodafone_records():
    return json.loads((FIXTURES / "vodafone_plans.json").read_text())["plans"]


def ee_records():
    body = json.loads((FIXTURES / "ee_plans.json").read_text())
    return body["data"]["simBundle"]["productPlanCombinations"]


RECORDS = {
    "Three": three_records,
    "Vodafone": vodafone_records,
    "EE": ee_records,
}


def all_offers():
    return [
        crawler().parse_record(record, crawler.START_URL, OBSERVED_AT)
        for crawler in CRAWLERS
        for record in RECORDS[crawler.competitor]()
    ]


def stored_row(offer):
    # What a row read back from BigQuery looks like
    return {
        "competitor": offer.competitor,
        "observed_at": offer.observed_at,
        "source_url": str(offer.source_url),
        "raw_text": offer.raw_text,
    }


def test_every_crawler_has_fixtures():
    assert {crawler.competitor for crawler in CRAWLERS} == set(RECORDS)


def test_reparse_rebuilds_identical_offers():
    for offer in all_offers():
        assert reparse_row(stored_row(offer)) == offer


def test_reparse_keeps_original_observation_time():
    earlier = datetime(2026, 1, 1, tzinfo=timezone.utc)
    offer = all_offers()[0]

    row = stored_row(offer) | {"observed_at": earlier}

    assert reparse_row(row).observed_at == earlier


def test_reparse_unknown_competitor_raises():
    row = stored_row(all_offers()[0]) | {"competitor": "O2"}

    with pytest.raises(KeyError):
        reparse_row(row)


def test_reparse_malformed_record_raises():
    row = stored_row(all_offers()[0]) | {"raw_text": json.dumps({"id": 1})}

    with pytest.raises(OfferParseError):
        reparse_row(row)


# --- Price rules shared by every competitor ----------------------------------

def test_monthly_price_never_above_list_price():
    for offer in all_offers():
        assert offer.monthly_price <= offer.list_monthly_price, offer.offer_id


def test_discount_months_only_set_for_discounted_offers():
    for offer in all_offers():
        if offer.monthly_price == offer.list_monthly_price:
            assert offer.discount_months is None, offer.offer_id


def test_discount_months_within_contract():
    for offer in all_offers():
        if offer.discount_months is not None:
            assert 0 < offer.discount_months <= offer.contract_term_months


def test_every_offer_has_a_total_and_average():
    # Every discount in the fixtures has a known length
    for offer in all_offers():
        assert offer.total_contract_price is not None, offer.offer_id
        assert offer.average_monthly_price is not None, offer.offer_id


def test_average_between_discounted_and_list_price():
    for offer in all_offers():
        assert (
            offer.monthly_price
            <= offer.average_monthly_price
            <= offer.list_monthly_price
        ), offer.offer_id


def test_data_is_unlimited_or_an_amount_or_explained():
    for offer in all_offers():
        if offer.unlimited_data:
            assert offer.data_allowance_gb is None
        elif offer.data_allowance_gb is None:
            # The only plan without an amount is EE's speed-capped
            # Protected Plan, labelled by its tier
            assert (offer.competitor, offer.plan_tier) == ("EE", "TEEN")
