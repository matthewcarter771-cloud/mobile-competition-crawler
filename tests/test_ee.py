import asyncio
import copy
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from crawler.competitors.base import OfferParseError
from crawler.competitors.ee import EECrawler
from tests.fakes import FakePage, FakeResponse

# Real plans captured from EE's SimBundleQuery GraphQL API on 2026-10-23
FIXTURE = Path(__file__).parent / "fixtures" / "ee_plans.json"

URL = EECrawler.START_URL
OBSERVED_AT = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)

FLASH_SALE_50GB = "X24XSL29"
DISCOUNTED_UNLIMITED = "X25XNSU07"   # £26, was £36
NO_DATA = "X25KSL10"                 # Protected Plan, calls and texts only
ONE_MONTH_UNLIMITED = "X24BS0114"
NO_LABELS = "X24ASU04"

GRAPHQL_URL = (
    "https://ee.co.uk/graphql?operationName=SimBundleQuery"
    "&variables=%7B%7D&extensions=%7B%7D"
)


@pytest.fixture
def body():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def combination(body):
    return copy.deepcopy(by_code(body, FLASH_SALE_50GB))


def combinations(body):
    return body["data"]["simBundle"]["productPlanCombinations"]


def by_code(body, code):
    return next(c for c in combinations(body) if c["plan"]["code"] == code)


def parse(combination):
    return EECrawler().parse_record(combination, URL, OBSERVED_AT)


def set_entitlement(combination, code, quantity):
    for entitlement in combination["plan"]["entitlements"]:
        if entitlement["code"] == code:
            entitlement["quantity"] = quantity


# --- Parsing real API data ---------------------------------------------------

def test_parses_every_fixture_plan(body):
    offers = [parse(c) for c in combinations(body)]

    assert [o.offer_id for o in offers] == [
        c["plan"]["code"] for c in combinations(body)
    ]
    assert all(o.competitor == "EE" for o in offers)
    assert all(o.offer_type == "SIM Only" for o in offers)


def test_flash_sale_plan(body):
    offer = parse(by_code(body, FLASH_SALE_50GB))

    assert offer.offer_name == "SIM 50GB 24m £13 T"
    assert offer.data_allowance_gb == 50.0
    assert offer.unlimited_data is False
    assert offer.contract_term_months == 24
    assert offer.monthly_price == Decimal("13.0")
    assert offer.minutes == "Unlimited"
    assert offer.texts == "Unlimited"
    assert offer.list_monthly_price == Decimal("13.0")
    assert offer.discount_months is None
    assert offer.plan_tier == "ESSENTIAL"
    assert offer.promotion_text == "Flash sale - ends 5 November"
    assert offer.promotion_ends_on == date(2026, 11, 5)


def test_discounted_plan_uses_price_paid(body):
    offer = parse(by_code(body, DISCOUNTED_UNLIMITED))

    assert offer.unlimited_data is True
    assert offer.data_allowance_gb is None
    assert offer.monthly_price == Decimal("26.0")
    assert offer.list_monthly_price == Decimal("36.0")
    assert offer.discount_months == 24
    assert offer.promotion_text == "Save £10 a month"


def test_plan_without_data_entitlement(body):
    offer = parse(by_code(body, NO_DATA))

    assert offer.offer_name == "Protected Plan"
    assert offer.plan_tier == "TEEN"
    assert offer.data_allowance_gb is None
    assert offer.unlimited_data is False
    assert offer.contract_term_months == 1


def test_one_month_plan(body):
    offer = parse(by_code(body, ONE_MONTH_UNLIMITED))

    assert offer.contract_term_months == 1
    assert offer.unlimited_data is True
    assert offer.monthly_price == Decimal("35.0")


def test_plan_without_labels(body):
    assert parse(by_code(body, NO_LABELS)).promotion_text is None


def test_multiple_labels_are_joined(combination):
    combination["plan"]["labels"].append({"title": "Extra 10GB"})

    assert parse(combination).promotion_text == (
        "Flash sale - ends 5 November | Extra 10GB"
    )


def test_raw_text_keeps_full_api_record(combination):
    assert json.loads(parse(combination).raw_text) == combination


def test_limited_minutes_are_kept_as_a_number(combination):
    set_entitlement(combination, "ME_PHONE_MIN", 500)

    assert parse(combination).minutes == "500"


# --- Malformed API data ------------------------------------------------------

@pytest.mark.parametrize("mutate, message", [
    (lambda c: c.pop("plan"),
     "EE plan <unknown>: expected plan to be dict"),
    (lambda c: c["plan"].pop("code"),
     "EE plan <unknown>: expected plan.code to be str"),
    (lambda c: c["plan"].pop("name"),
     "expected plan.name to be str"),
    (lambda c: c["plan"].pop("price"),
     "expected plan.price to be dict"),
    (lambda c: c["plan"]["price"].update(payMonthlyPrice="13"),
     "expected plan.price.payMonthlyPrice to be int or float"),
    (lambda c: c["plan"]["price"].pop("payMonthlyPrice"),
     "expected plan.price.payMonthlyPrice to be int or float"),
    (lambda c: c["plan"]["price"].update(subscriptionTermInMonths=24.0),
     "expected plan.price.subscriptionTermInMonths to be int"),
    (lambda c: c["plan"]["price"].update(wasPayMonthlyPrice="36"),
     "expected plan.price.wasPayMonthlyPrice to be int or float"),
    (lambda c: c["plan"]["price"].update(wasPayMonthlyPrice=10.0),
     "wasPayMonthlyPrice 10.0 is below payMonthlyPrice 13.0"),
    (lambda c: c["plan"].pop("planFamily"),
     "expected plan.planFamily to be dict"),
    (lambda c: c["plan"].pop("entitlements"),
     "expected plan.entitlements to be list"),
    (lambda c: set_entitlement(c, "ME_DATA_MB", "50000"),
     "expected plan.entitlements[ME_DATA_MB].quantity to be int"),
    (lambda c: set_entitlement(c, "ME_DATA_MB", -2),
     "unexpected ME_DATA_MB quantity -2"),
    (lambda c: c["plan"].pop("labels"),
     "expected plan.labels to be list"),
], ids=[
    "missing plan", "missing code", "missing name", "missing price",
    "price is string", "missing price amount", "term is float",
    "was price is string", "was price below price", "missing planFamily",
    "missing entitlements", "data is string",
    "data below -1", "missing labels",
])
def test_malformed_plan_raises_descriptive_error(combination, mutate, message):
    mutate(combination)

    with pytest.raises(OfferParseError, match=re.escape(message)):
        parse(combination)


def test_error_names_the_plan(combination):
    combination["plan"].pop("price")

    with pytest.raises(OfferParseError, match=f"EE plan {FLASH_SALE_50GB}"):
        parse(combination)


# --- extract_offers with a fake Playwright page ------------------------------

def extract(page):
    return asyncio.run(EECrawler().extract_offers(page, URL))


def test_extract_offers_parses_graphql_response(body):
    page = FakePage(FakeResponse(GRAPHQL_URL, body))

    offers = extract(page)

    assert page.visited == [URL]
    assert len(offers) == len(combinations(body))


def test_extract_offers_waits_for_sim_bundle_query_only(body):
    page = FakePage(FakeResponse(GRAPHQL_URL, body))
    extract(page)

    assert page.predicate(FakeResponse(GRAPHQL_URL, None))
    assert not page.predicate(FakeResponse(GRAPHQL_URL, None, method="POST"))
    assert not page.predicate(FakeResponse(
        "https://ee.co.uk/graphql?operationName=GeneralCmsSlotQuery", None
    ))


def test_extract_offers_raises_on_graphql_errors():
    body = {"errors": [{"message": "PersistedQueryNotFound"}], "data": None}
    page = FakePage(FakeResponse(GRAPHQL_URL, body))

    with pytest.raises(OfferParseError, match="PersistedQueryNotFound"):
        extract(page)


def test_extract_offers_raises_on_http_error():
    page = FakePage(FakeResponse(GRAPHQL_URL, None, status=500))

    with pytest.raises(RuntimeError, match="HTTP 500"):
        extract(page)


@pytest.mark.parametrize("body", [
    {"data": {"simBundle": {"productPlanCombinations": []}}},
    {"data": {"simBundle": None}},
    {"data": None},
    {},
    None,
])
def test_extract_offers_raises_on_empty_response(body):
    page = FakePage(FakeResponse(GRAPHQL_URL, body))

    with pytest.raises(OfferParseError, match="returned no plans"):
        extract(page)
