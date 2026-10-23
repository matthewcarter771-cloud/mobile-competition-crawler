import asyncio
import copy
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from crawler.competitors.base import OfferParseError
from crawler.competitors.parsing import to_decimal
from crawler.competitors.three import ThreeCrawler, parse_intro_months
from tests.fakes import FakePage, FakeResponse

# Real offerings captured from Three's mobileOffering API on 2026-10-23
FIXTURE = Path(__file__).parent / "fixtures" / "three_offerings.json"

URL = ThreeCrawler.START_URL
OBSERVED_AT = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)

HALF_PRICE_120GB = "1467471_1465711_1455891"
UNLIMITED_24M = "449527_449547_309697"
FLASH_SALE_20GB = "48533090_48533290_48506590"
NO_BADGE_4GB = "438487_438507_304767"


@pytest.fixture
def offerings():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def offering(offerings):
    # A fresh copy of the 120GB plan for each test to mutate
    return copy.deepcopy(by_id(offerings, HALF_PRICE_120GB))


def by_id(offerings, offering_id):
    return next(o for o in offerings if o["id"] == offering_id)


def parse(offering):
    return ThreeCrawler().parse_record(offering, URL, OBSERVED_AT)


def set_characteristic(offering, name, value):
    for item in offering["plan"]["descriptiveCharacteristic"]:
        if item["name"] == name:
            item["value"] = value


# --- Parsing real API data ---------------------------------------------------

def test_parses_every_fixture_offering(offerings):
    offers = [parse(o) for o in offerings]

    assert [o.offer_id for o in offers] == [o["id"] for o in offerings]
    assert all(o.competitor == "Three" for o in offers)
    assert all(o.offer_type == "SIM Only" for o in offers)
    assert all(o.observed_at == OBSERVED_AT for o in offers)


def test_half_price_plan(offerings):
    offer = parse(by_id(offerings, HALF_PRICE_120GB))

    assert offer.offer_name == "120GB Lite SIMO 24M"
    assert offer.data_allowance_gb == 120.0
    assert offer.unlimited_data is False
    assert offer.contract_term_months == 24
    assert offer.monthly_price == Decimal("8.0")
    assert offer.list_monthly_price == Decimal("16.0")
    assert offer.discount_months == 6
    assert offer.plan_tier == "Lite"
    assert offer.promotion_text == "6 months half price"
    assert offer.promotion_code is None
    assert offer.promotion_ends_on is None
    assert offer.minutes == "Unlimited"
    assert offer.texts == "Unlimited"


def test_unlimited_plan_with_non_discount_badge(offerings):
    offer = parse(by_id(offerings, UNLIMITED_24M))

    assert offer.unlimited_data is True
    assert offer.data_allowance_gb is None
    # The code discount needs the customer to enter it, so isn't applied
    assert offer.monthly_price == Decimal("22.0")
    assert offer.list_monthly_price == Decimal("22.0")
    assert offer.discount_months is None
    assert offer.promotion_text == "Get £2 off a month with code 2OFF"
    assert offer.promotion_code == "2OFF"


def test_plan_without_badge(offerings):
    offer = parse(by_id(offerings, NO_BADGE_4GB))

    assert offer.data_allowance_gb == 4.0
    assert offer.promotion_text is None
    assert offer.monthly_price == offer.list_monthly_price


def test_one_month_plan_reads_intro_months_from_sentence_badge(offerings):
    offering = next(
        o for o in offerings if o["displayName"] == "Unlimited Lite SIMO 1M"
    )
    offer = parse(offering)

    assert offer.contract_term_months == 1
    assert offer.monthly_price == Decimal("18.0")
    assert offer.list_monthly_price == Decimal("36.0")
    assert offer.discount_months == 1


def test_raw_text_keeps_full_api_record(offerings):
    offering = by_id(offerings, FLASH_SALE_20GB)

    assert json.loads(parse(offering).raw_text) == offering


# --- Price and commitment selection ------------------------------------------

def test_monthly_price_chosen_by_type_not_position(offering):
    offering["offeringPrice"].insert(0, {
        "type": "oneTime",
        "price": {"currencyCode": "GBP", "taxIncludedAmount": 5.0},
    })

    assert parse(offering).list_monthly_price == Decimal("16.0")


def test_commitment_chosen_by_unit_not_position(offering):
    offering["commitment"].insert(0, {"duration": 30, "unitOfMeasure": "days"})

    assert parse(offering).contract_term_months == 24


def test_prices_converted_exactly():
    assert to_decimal(10.5) == Decimal("10.5")
    assert to_decimal(0.1) == Decimal("0.1")
    assert to_decimal(None) is None


# --- Introductory price / duration reconciliation ----------------------------

@pytest.mark.parametrize("badge, list_price, discounted, expected", [
    ("6 months half price", "16", "8", 6),
    ("12 months half price", "26", "13", 12),
    ("From £18, 1 month half price.", "36", "18", 1),
    # Badge and discountedMRC describe different discounts
    ("6 months half price", "16", "10", None),
    # Badge says nothing about a duration
    ("Great value", "16", "8", None),
    ("Get £2 off a month with code 2OFF", "22", "20", None),
    # Missing badge or missing discount
    (None, "16", "8", None),
    ("6 months half price", "16", None, None),
])
def test_parse_intro_months(badge, list_price, discounted, expected):
    result = parse_intro_months(
        badge,
        Decimal(list_price),
        Decimal(discounted) if discounted else None,
    )

    assert result == expected


def test_discount_without_matching_badge_keeps_price_but_not_duration(
    offering,
):
    offering["plan"]["discountedMRC"] = 10.0

    offer = parse(offering)

    assert offer.monthly_price == Decimal("10.0")
    assert offer.list_monthly_price == Decimal("16.0")
    assert offer.discount_months is None
    assert offer.promotion_text == "6 months half price"


# --- Malformed API data ------------------------------------------------------

def remove_data_characteristic(o):
    o["plan"]["descriptiveCharacteristic"] = [
        c for c in o["plan"]["descriptiveCharacteristic"]
        if c["name"] != "Data"
    ]


@pytest.mark.parametrize("mutate, message", [
    (lambda o: o.pop("id"),
     "Three offering <unknown>: expected id to be str"),
    (lambda o: o.pop("plan"),
     "expected plan to be dict"),
    (lambda o: o.pop("displayName"),
     "expected displayName to be str"),
    (lambda o: o.pop("offeringPrice"),
     "expected offeringPrice to be list"),
    (lambda o: o["offeringPrice"].append(copy.deepcopy(o["offeringPrice"][0])),
     "expected exactly one monthly recurring price in offeringPrice, found 2"),
    (lambda o: o["offeringPrice"][0].update(recurringChargePeriod="year"),
     "expected exactly one monthly recurring price in offeringPrice, found 0"),
    (lambda o: o["offeringPrice"][0]["price"].update(currencyCode="EUR"),
     "expected GBP price, got EUR"),
    (lambda o: o["offeringPrice"][0]["price"].update(taxIncludedAmount="16"),
     "taxIncludedAmount to be int or float"),
    (lambda o: o["offeringPrice"][0]["price"].update(taxIncludedAmount=True),
     "taxIncludedAmount to be int or float"),
    (lambda o: o.update(commitment=[]),
     "expected exactly one commitment in months, found 0"),
    (lambda o: o["commitment"][0].update(duration="24"),
     "expected commitment[months].duration to be int"),
    (lambda o: o["plan"].update(discountedMRC="8"),
     "expected plan.discountedMRC to be int or float"),
    (lambda o: o["plan"].update(discountedMRC=20.0),
     "discountedMRC 20.0 is above the list price 16.0"),
    (lambda o: o["plan"].update(descriptiveCharacteristic={}),
     "expected plan.descriptiveCharacteristic to be a list"),
    (remove_data_characteristic,
     "no Data characteristic"),
    (lambda o: set_characteristic(o, "Data", [{"value": "Lots"}]),
     "unrecognised Data value 'Lots'"),
    (lambda o: set_characteristic(o, "Minutes", [{"value": 100}]),
     "expected characteristic 'Minutes' to have a string value"),
    (lambda o: o["plan"]["planEnrichedAttributes"].update(
        b2cAcquisitionPlanBadgeText=["6 months half price"]),
     "b2cAcquisitionPlanBadgeText to be str"),
], ids=[
    "missing id", "missing plan", "missing displayName",
    "missing offeringPrice", "two monthly prices", "no monthly price",
    "non-GBP price", "price is string", "price is bool",
    "no commitment", "duration is string", "discountedMRC is string",
    "discount above list price",
    "characteristics not a list", "no Data", "unrecognised Data",
    "Minutes not a string", "badge not a string",
])
def test_malformed_offering_raises_descriptive_error(offering, mutate, message):
    mutate(offering)

    with pytest.raises(OfferParseError, match=re.escape(message)):
        parse(offering)


def test_error_names_the_offering(offering):
    offering.pop("offeringPrice")

    with pytest.raises(OfferParseError, match=f"Three offering {HALF_PRICE_120GB}"):
        parse(offering)


def test_non_object_offering_raises():
    with pytest.raises(OfferParseError, match="not an object"):
        parse(["junk"])


def test_unnamed_characteristic_is_ignored(offering):
    offering["plan"]["descriptiveCharacteristic"].insert(0, {"value": []})

    assert parse(offering).data_allowance_gb == 120.0


def test_empty_optional_characteristic_is_none(offering):
    set_characteristic(offering, "Minutes", [])

    assert parse(offering).minutes is None


# --- extract_offers with a fake Playwright page ------------------------------

API_URL = (
    "https://www.three.co.uk/rp-server-b2c/commerce/v1/B2C/mobileOffering"
    "?salesChannel=selfService&offset=0"
)


def extract(page):
    return asyncio.run(ThreeCrawler().extract_offers(page, URL))


def test_extract_offers_parses_api_response(offerings):
    page = FakePage(FakeResponse(API_URL, offerings))

    offers = extract(page)

    assert page.visited == [URL]
    assert [o.offer_id for o in offers] == [o["id"] for o in offerings]
    assert len({o.observed_at for o in offers}) == 1


def test_extract_offers_waits_for_the_offerings_api_only(offerings):
    page = FakePage(FakeResponse(API_URL, offerings))
    extract(page)

    assert page.predicate(FakeResponse(API_URL, None))
    assert not page.predicate(FakeResponse(API_URL, None, method="POST"))
    assert not page.predicate(FakeResponse(
        "https://www.three.co.uk/rp-server-b2c/commerce/v1/B2C/category",
        None,
    ))


def test_extract_offers_raises_on_http_error():
    page = FakePage(FakeResponse(API_URL, None, status=503))

    with pytest.raises(RuntimeError, match="HTTP 503"):
        extract(page)


@pytest.mark.parametrize("body", [[], {}, None, {"error": "x"}])
def test_extract_offers_raises_on_empty_or_non_list_response(body):
    page = FakePage(FakeResponse(API_URL, body))

    with pytest.raises(OfferParseError, match="returned no offerings"):
        extract(page)
