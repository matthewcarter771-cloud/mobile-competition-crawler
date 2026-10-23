import json
import re
from datetime import datetime, timezone
from decimal import Decimal

from crawler.competitors.base import BaseCompetitionCrawler, OfferParseError
from crawler.competitors.parsing import (
    parse_data,
    promotion_fields,
    require,
    to_decimal,
)
from crawler.models import MobileOffer


class ThreeCrawler(BaseCompetitionCrawler):

    competitor = "Three"

    START_URL = "https://www.three.co.uk/shop/sim-only/pay-monthly"

    # The catalogue page builds its plan picker from this API response,
    # which has every plan with structured prices
    OFFERINGS_API_PATH = "/rp-server-b2c/commerce/v1/B2C/mobileOffering"

    async def discover_offer_urls(self, page):
        return [self.START_URL]

    async def extract_offers(self, page, url):

        # Capture the API response the page fetches itself rather than
        # scraping the HTML, so layout changes don't break the crawler
        async with page.expect_response(
            lambda r: self.OFFERINGS_API_PATH in r.url
            and r.request.method == "GET",
            timeout=30000
        ) as response_info:
            await page.goto(
                url,
                wait_until="domcontentloaded"
            )

        response = await response_info.value

        if not response.ok:
            raise RuntimeError(
                f"Three offerings API returned HTTP {response.status}"
            )

        offerings = await response.json()

        # An empty or non-list response means the API has changed, not
        # that Three has no plans, so fail loudly rather than return []
        if not isinstance(offerings, list) or not offerings:
            raise OfferParseError(
                "Three offerings API returned no offerings: "
                f"{json.dumps(offerings)[:200]}"
            )

        print(f"Found {len(offerings)} offerings in API response")

        observed_at = datetime.now(timezone.utc)

        return [
            self.parse_record(offering, url, observed_at)
            for offering in offerings
        ]

    def parse_record(self, offering, url, observed_at):
        if not isinstance(offering, dict):
            raise OfferParseError(
                f"Three offering is not an object: {json.dumps(offering)[:200]}"
            )

        offering_id = require(
            offering, "id", str, "Three offering <unknown>", "id"
        )
        context = f"Three offering {offering_id}"

        plan = require(offering, "plan", dict, context, "plan")

        data = characteristic(plan, "Data", context)
        if data is None:
            raise OfferParseError(f"{context}: no Data characteristic")

        unlimited_data = data.lower() == "unlimited"
        data_allowance_gb = parse_data(data)
        if not unlimited_data and data_allowance_gb is None:
            raise OfferParseError(
                f"{context}: unrecognised Data value {data!r}"
            )

        enriched = plan.get("planEnrichedAttributes") or {}
        badge = enriched.get("b2cAcquisitionPlanBadgeText")
        if badge is not None and not isinstance(badge, str):
            raise OfferParseError(
                f"{context}: expected "
                f"plan.planEnrichedAttributes.b2cAcquisitionPlanBadgeText "
                f"to be str, got {badge!r}"
            )

        list_price = monthly_list_price(offering, context)

        discounted_price = plan.get("discountedMRC")
        if discounted_price is not None:
            discounted_price = to_decimal(require(
                plan, "discountedMRC", (int, float),
                context, "plan.discountedMRC"
            ))

            if discounted_price > list_price:
                raise OfferParseError(
                    f"{context}: discountedMRC {discounted_price} is above "
                    f"the list price {list_price}"
                )

        return MobileOffer(
            observed_at=observed_at,
            competitor=self.competitor,
            source_url=url,
            offer_type="SIM Only",
            offer_id=offering_id,
            offer_name=require(
                offering, "displayName", str, context, "displayName"
            ),
            plan_tier=characteristic(plan, "Plan_Type", context),
            data_allowance_gb=data_allowance_gb,
            unlimited_data=unlimited_data,
            contract_term_months=contract_term_months(offering, context),
            # discountedMRC is a time-limited discount, e.g. "6 months half
            # price", after which the list price applies
            monthly_price=(
                discounted_price if discounted_price is not None
                else list_price
            ),
            list_monthly_price=list_price,
            discount_months=parse_intro_months(
                badge, list_price, discounted_price
            ),
            minutes=characteristic(plan, "Minutes", context),
            texts=characteristic(plan, "Text", context),
            **promotion_fields(badge, observed_at),
            raw_text=json.dumps(offering)
        )


def monthly_list_price(offering: dict, context: str) -> Decimal:
    # Pick the price by what it is, not by its position in the list, and
    # refuse to guess if the API ever returns more than one candidate
    prices = require(offering, "offeringPrice", list, context, "offeringPrice")

    monthly = [
        price for price in prices
        if isinstance(price, dict)
        and price.get("type") == "recurring"
        and price.get("recurringChargePeriod") == "month"
    ]

    if len(monthly) != 1:
        raise OfferParseError(
            f"{context}: expected exactly one monthly "
            f"recurring price in offeringPrice, found {len(monthly)}"
        )

    path = "offeringPrice[recurring/month].price"
    price = require(monthly[0], "price", dict, context, path)

    currency = require(
        price, "currencyCode", str, context, f"{path}.currencyCode"
    )
    if currency != "GBP":
        raise OfferParseError(f"{context}: expected GBP price, got {currency}")

    return to_decimal(require(
        price, "taxIncludedAmount", (int, float),
        context, f"{path}.taxIncludedAmount"
    ))


def contract_term_months(offering: dict, context: str) -> int:
    commitments = require(offering, "commitment", list, context, "commitment")

    in_months = [
        commitment for commitment in commitments
        if isinstance(commitment, dict)
        and commitment.get("unitOfMeasure") == "months"
    ]

    if len(in_months) != 1:
        raise OfferParseError(
            f"{context}: expected exactly one commitment "
            f"in months, found {len(in_months)}"
        )

    return require(
        in_months[0], "duration", int,
        context, "commitment[months].duration"
    )


def characteristic(plan: dict, name: str, context: str) -> str | None:
    items = plan.get("descriptiveCharacteristic", [])
    if not isinstance(items, list):
        raise OfferParseError(
            f"{context}: expected "
            f"plan.descriptiveCharacteristic to be a list"
        )

    for item in items:
        if not isinstance(item, dict) or item.get("name") != name:
            continue

        values = item.get("value") or []
        if isinstance(values, list) and not values:
            return None

        first = values[0] if isinstance(values, list) else None
        value = first.get("value") if isinstance(first, dict) else None
        if not isinstance(value, str):
            raise OfferParseError(
                f"{context}: expected characteristic "
                f"{name!r} to have a string value, got "
                f"{json.dumps(item.get('value'))[:100]}"
            )

        return value

    return None


def parse_intro_months(
    badge: str | None,
    list_price: Decimal,
    discounted_price: Decimal | None
) -> int | None:
    # The API gives the discounted price (discountedMRC) but its duration
    # only appears in the badge text, e.g. "6 months half price". Only use
    # the badge's month count when it describes that same discount, i.e.
    # it says "half price" and discountedMRC really is half the list price.
    # Otherwise leave the duration unknown; the badge is still kept in
    # promotion_text
    if badge is None or discounted_price is None:
        return None

    match = re.search(r"(\d+)\s*months?\s+half\s+price", badge.lower())
    if not match or discounted_price * 2 != list_price:
        return None

    return int(match.group(1))
