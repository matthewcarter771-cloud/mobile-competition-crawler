import asyncio
import copy
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from crawler.competitors.base import OfferParseError
from crawler.competitors.vodafone import VodafoneCrawler
from tests.fakes import FakePage, FakeResponse

# Real plans captured from Vodafone's SIM only plans API on 2026-10-23
FIXTURE = Path(__file__).parent / "fixtures" / "vodafone_plans.json"

URL = VodafoneCrawler.START_URL
OBSERVED_AT = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)

FULL_CONTRACT_DISCOUNT = "127121"   # Unlimited Plus, £26 instead of £43
SASH_BANNER = "123040"              # 100GB, marketing label only
HALF_GB = "113913"                  # 500MB Basics
ONE_MONTH = "123034"                # 5GB rolling
NO_PROMOTION = "123048"             # Unlimited, no promotion
TWELVE_MONTH_DISCOUNT = "123089"    # 16GB Basics, £10 off for the contract

PLANS_URL = (
    "https://www.vodafone.co.uk/sim-only/best-sim-only-deals/api/digital/v2"
    "/simo-purchase/paym/v2/session/journeys/journey/plans"
    "?linesQuantity=1&sortBy="
)


@pytest.fixture
def body():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def plan(body):
    return copy.deepcopy(by_id(body, NO_PROMOTION))


def by_id(body, plan_id):
    return next(p for p in body["plans"] if p["id"] == plan_id)


def parse(plan):
    return VodafoneCrawler().parse_plan(plan, URL, OBSERVED_AT)


def set_allowance(plan, kind, value, uom):
    for allowance in plan["allowances"]:
        if allowance["type"] == kind:
            allowance.update(value=value, uom=uom)


# --- Parsing real API data ---------------------------------------------------

def test_parses_every_fixture_plan(body):
    offers = [parse(p) for p in body["plans"]]

    assert [o.offer_id for o in offers] == [p["id"] for p in body["plans"]]
    assert all(o.competitor == "Vodafone" for o in offers)
    assert all(o.offer_type == "SIM Only" for o in offers)
    assert all(o.minutes == "Unlimited" for o in offers)
    assert all(o.texts == "Unlimited" for o in offers)


def test_full_contract_discount_is_the_monthly_price(body):
    offer = parse(by_id(body, FULL_CONTRACT_DISCOUNT))

    assert offer.offer_name == "Unlimited Plus"
    assert offer.unlimited_data is True
    assert offer.data_allowance_gb is None
    assert offer.contract_term_months == 24
    assert offer.monthly_price == Decimal("26")
    assert offer.introductory_price is None
    assert offer.promotion_text == "Great Low Price"


def test_twelve_month_discounted_plan(body):
    offer = parse(by_id(body, TWELVE_MONTH_DISCOUNT))

    assert offer.contract_term_months == 12
    assert offer.data_allowance_gb == 16.0
    assert offer.monthly_price == Decimal("7")
    assert offer.promotion_text == "Includes £10 a month discount"


def test_sash_banner_is_promotion_text_only(body):
    offer = parse(by_id(body, SASH_BANNER))

    # DATA includes the 20GB bonus on top of the 80GB ORIGDATA
    assert offer.data_allowance_gb == 100.0
    assert offer.monthly_price == Decimal("24")
    assert offer.promotion_text == "Yours for a great price"


def test_megabyte_allowance_converted_to_gb(body):
    offer = parse(by_id(body, HALF_GB))

    assert offer.data_allowance_gb == 0.5
    assert offer.monthly_price == Decimal("7.87")


def test_one_month_plan(body):
    offer = parse(by_id(body, ONE_MONTH))

    assert offer.contract_term_months == 1
    assert offer.data_allowance_gb == 5.0
    assert offer.promotion_text is None


def test_raw_text_keeps_full_api_record(body):
    plan = by_id(body, NO_PROMOTION)

    assert json.loads(parse(plan).raw_text) == plan


# --- Discount handling -------------------------------------------------------

def test_discount_under_unknown_promotion_type_raises(plan):
    plan["primaryPromotion"] = {"type": "first_6_months", "name": "Half price"}
    plan["monthlyPrice"]["gross"]["value"] = 17.5

    with pytest.raises(OfferParseError, match="unrecognised promotion type"):
        parse(plan)


def test_discount_without_promotion_raises(plan):
    plan["monthlyPrice"]["gross"]["value"] = 20

    with pytest.raises(OfferParseError, match="differs from original"):
        parse(plan)


def test_unknown_promotion_type_without_price_change_is_fine(plan):
    plan["primaryPromotion"] = {"type": "new_label", "name": "Hot deal"}

    assert parse(plan).promotion_text == "Hot deal"


# --- Malformed API data ------------------------------------------------------

@pytest.mark.parametrize("mutate, message", [
    (lambda p: p.pop("id"),
     "Vodafone plan <unknown>: expected id to be str"),
    (lambda p: p.pop("name"),
     "expected name to be str"),
    (lambda p: p.pop("allowances"),
     "expected allowances to be list"),
    (lambda p: p.update(allowances=[a for a in p["allowances"] if a["type"] != "DATA"]),
     "no DATA allowance"),
    (lambda p: set_allowance(p, "DATA", "Lots", "-"),
     "unrecognised DATA value 'Lots'"),
    (lambda p: set_allowance(p, "DATA", 100, "GB"),
     "expected allowances[DATA].value to be str"),
    (lambda p: p.pop("monthlyPrice"),
     "expected monthlyPrice to be dict"),
    (lambda p: p["monthlyPrice"]["gross"].update(uom="EUR"),
     "expected GBP monthlyPrice, got EUR"),
    (lambda p: p["monthlyPrice"]["gross"].update(value="35"),
     "expected monthlyPrice.gross.value to be int or float"),
    (lambda p: p.pop("originalMonthlyPrice"),
     "expected originalMonthlyPrice to be dict"),
    (lambda p: p.update(commitmentPeriod="24 weeks"),
     "unrecognised commitmentPeriod '24 weeks'"),
    (lambda p: p.update(primaryPromotion="sale"),
     "expected primaryPromotion to be dict"),
], ids=[
    "missing id", "missing name", "missing allowances", "no DATA",
    "unrecognised DATA", "DATA not a string", "missing monthlyPrice",
    "non-GBP price", "price is string", "missing originalMonthlyPrice",
    "unrecognised commitment", "promotion not a dict",
])
def test_malformed_plan_raises_descriptive_error(plan, mutate, message):
    mutate(plan)

    with pytest.raises(OfferParseError, match=re.escape(message)):
        parse(plan)


def test_error_names_the_plan(plan):
    plan.pop("monthlyPrice")

    with pytest.raises(OfferParseError, match=f"Vodafone plan {NO_PROMOTION}"):
        parse(plan)


# --- extract_offers with a fake Playwright page ------------------------------

def extract(page):
    return asyncio.run(VodafoneCrawler().extract_offers(page, URL))


def test_extract_offers_parses_api_response(body):
    page = FakePage(FakeResponse(PLANS_URL, body))

    offers = extract(page)

    assert page.visited == [URL]
    assert [o.offer_id for o in offers] == [p["id"] for p in body["plans"]]


def test_extract_offers_waits_for_the_unfiltered_plans_call(body):
    page = FakePage(FakeResponse(PLANS_URL, body))
    extract(page)

    filtered = PLANS_URL.replace("plans?", "plans?commitmentPeriod=24+Months&")
    assert page.predicate(FakeResponse(PLANS_URL, None))
    assert not page.predicate(FakeResponse(filtered, None))
    assert not page.predicate(FakeResponse(PLANS_URL, None, method="PATCH"))
    assert not page.predicate(FakeResponse(
        PLANS_URL.replace("/plans?", "/latest?"), None
    ))


def test_extract_offers_raises_on_http_error():
    page = FakePage(FakeResponse(PLANS_URL, None, status=503))

    with pytest.raises(RuntimeError, match="HTTP 503"):
        extract(page)


@pytest.mark.parametrize("body", [{"plans": []}, {}, [], None])
def test_extract_offers_raises_on_empty_response(body):
    page = FakePage(FakeResponse(PLANS_URL, body))

    with pytest.raises(OfferParseError, match="returned no plans"):
        extract(page)
