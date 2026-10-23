import json
import re
from datetime import datetime, timezone

from crawler.competitors.base import BaseCompetitionCrawler, OfferParseError
from crawler.competitors.parsing import parse_data, require, to_decimal
from crawler.models import MobileOffer


class VodafoneCrawler(BaseCompetitionCrawler):

    competitor = "Vodafone"

    START_URL = "https://www.vodafone.co.uk/sim-only/best-sim-only-deals"

    # The SIM only page loads its plans from this API. It makes two calls:
    # one filtered to the default 24 month tab, and one unfiltered call
    # with every contract length, which is the one we want
    PLANS_API_PATH = "/simo-purchase/paym/v2/"

    # Promotions whose discount lasts the whole contract, so the discounted
    # price is the contract's monthly price. "sash_banner" is a marketing
    # label with no price change
    FULL_CONTRACT_PROMOTIONS = {"full_duration"}

    async def discover_offer_urls(self, page):
        return [self.START_URL]

    async def extract_offers(self, page, url):

        async with page.expect_response(
            lambda r: is_unfiltered_plans_response(r, self.PLANS_API_PATH),
            timeout=30000
        ) as response_info:
            await page.goto(url, wait_until="domcontentloaded")

        response = await response_info.value

        if not response.ok:
            raise RuntimeError(
                f"Vodafone plans API returned HTTP {response.status}"
            )

        body = await response.json()
        plans = body.get("plans") if isinstance(body, dict) else None

        if not isinstance(plans, list) or not plans:
            raise OfferParseError(
                "Vodafone plans API returned no plans: "
                f"{json.dumps(body)[:200]}"
            )

        print(f"Found {len(plans)} plans in API response")

        observed_at = datetime.now(timezone.utc)

        return [self.parse_plan(plan, url, observed_at) for plan in plans]

    def parse_plan(self, plan, url, observed_at):
        if not isinstance(plan, dict):
            raise OfferParseError(
                f"Vodafone plan is not an object: {json.dumps(plan)[:200]}"
            )

        plan_id = require(plan, "id", str, "Vodafone plan <unknown>", "id")
        context = f"Vodafone plan {plan_id}"

        allowances = parse_allowances(plan, context)

        data = allowances.get("DATA")
        if data is None:
            raise OfferParseError(f"{context}: no DATA allowance")

        unlimited_data = data.lower() == "unlimited"
        data_allowance_gb = parse_data(data)
        if not unlimited_data and data_allowance_gb is None:
            raise OfferParseError(f"{context}: unrecognised DATA value {data!r}")

        price = gross_price(plan, "monthlyPrice", context)
        original_price = gross_price(plan, "originalMonthlyPrice", context)

        promotion = plan.get("primaryPromotion") or {}
        if not isinstance(promotion, dict):
            raise OfferParseError(
                f"{context}: expected primaryPromotion to be dict"
            )

        promotion_type = promotion.get("type")
        promotion_name = promotion.get("name")
        if promotion_name is not None and not isinstance(promotion_name, str):
            raise OfferParseError(
                f"{context}: expected primaryPromotion.name to be str"
            )

        # A discount that isn't known to last the whole contract could be
        # time-limited, and the API doesn't say for how long, so refuse
        # to guess which price is the contract price
        if (
            price != original_price
            and promotion_type not in self.FULL_CONTRACT_PROMOTIONS
        ):
            raise OfferParseError(
                f"{context}: price {price} differs from original "
                f"{original_price} under unrecognised promotion type "
                f"{promotion_type!r}"
            )

        return MobileOffer(
            observed_at=observed_at,
            competitor=self.competitor,
            source_url=url,
            offer_type="SIM Only",
            offer_id=plan_id,
            offer_name=require(plan, "name", str, context, "name"),
            data_allowance_gb=data_allowance_gb,
            unlimited_data=unlimited_data,
            contract_term_months=parse_commitment(plan, context),
            monthly_price=price,
            minutes=allowances.get("MIN"),
            texts=allowances.get("TEXT"),
            promotion_text=promotion_name,
            raw_text=json.dumps(plan)
        )


def is_unfiltered_plans_response(response, api_path: str) -> bool:
    url = response.url
    return (
        response.request.method == "GET"
        and api_path in url
        and "/plans?" in url
        and "commitmentPeriod=" not in url
    )


def parse_allowances(plan: dict, context: str) -> dict[str, str]:
    allowances = require(plan, "allowances", list, context, "allowances")

    parsed = {}
    for allowance in allowances:
        if not isinstance(allowance, dict):
            raise OfferParseError(f"{context}: allowance is not an object")

        kind = require(
            allowance, "type", str, context, "allowances[].type"
        )
        value = require(
            allowance, "value", str, context, f"allowances[{kind}].value"
        )
        unit = require(
            allowance, "uom", str, context, f"allowances[{kind}].uom"
        )

        # The amount and unit are separate, e.g. {"value": "1", "uom": "GB"};
        # "-" means no unit, as in {"value": "Unlimited", "uom": "-"}
        parsed[kind] = value if unit == "-" else f"{value}{unit}"

    return parsed


def gross_price(plan: dict, key: str, context: str):
    price = require(plan, key, dict, context, key)
    gross = require(price, "gross", dict, context, f"{key}.gross")

    currency = require(gross, "uom", str, context, f"{key}.gross.uom")
    if currency != "GBP":
        raise OfferParseError(
            f"{context}: expected GBP {key}, got {currency}"
        )

    return to_decimal(require(
        gross, "value", (int, float), context, f"{key}.gross.value"
    ))


def parse_commitment(plan: dict, context: str) -> int:
    # e.g. "24 Months", "1 Months"
    commitment = require(
        plan, "commitmentPeriod", str, context, "commitmentPeriod"
    )

    match = re.fullmatch(r"(\d+) Months?", commitment.strip())
    if not match:
        raise OfferParseError(
            f"{context}: unrecognised commitmentPeriod {commitment!r}"
        )

    return int(match.group(1))
