import json
from datetime import datetime, timezone

from crawler.competitors.base import BaseCompetitionCrawler, OfferParseError
from crawler.competitors.parsing import require, to_decimal
from crawler.models import MobileOffer


class EECrawler(BaseCompetitionCrawler):

    competitor = "EE"

    START_URL = "https://ee.co.uk/mobile/sim-only-deals"

    # The SIM only page loads every pay monthly SIM plan from this
    # GraphQL query
    GRAPHQL_OPERATION = "operationName=SimBundleQuery"

    async def discover_offer_urls(self, page):
        return [self.START_URL]

    async def extract_offers(self, page, url):

        async with page.expect_response(
            lambda r: "/graphql" in r.url
            and self.GRAPHQL_OPERATION in r.url
            and r.request.method == "GET",
            timeout=30000
        ) as response_info:
            await page.goto(url, wait_until="domcontentloaded")

        response = await response_info.value

        if not response.ok:
            raise RuntimeError(f"EE GraphQL API returned HTTP {response.status}")

        body = await response.json()

        if isinstance(body, dict) and body.get("errors"):
            raise OfferParseError(
                f"EE GraphQL API returned errors: "
                f"{json.dumps(body['errors'])[:200]}"
            )

        combinations = (
            ((body.get("data") or {}).get("simBundle") or {})
            .get("productPlanCombinations")
            if isinstance(body, dict) else None
        )

        if not isinstance(combinations, list) or not combinations:
            raise OfferParseError(
                f"EE GraphQL API returned no plans: {json.dumps(body)[:200]}"
            )

        print(f"Found {len(combinations)} plans in API response")

        observed_at = datetime.now(timezone.utc)

        return [
            self.parse_combination(combination, url, observed_at)
            for combination in combinations
        ]

    def parse_combination(self, combination, url, observed_at):
        if not isinstance(combination, dict):
            raise OfferParseError(
                f"EE plan is not an object: {json.dumps(combination)[:200]}"
            )

        plan = require(combination, "plan", dict, "EE plan <unknown>", "plan")
        code = require(plan, "code", str, "EE plan <unknown>", "plan.code")
        context = f"EE plan {code}"

        price = require(plan, "price", dict, context, "plan.price")

        entitlements = parse_entitlements(plan, context)
        data_mb = entitlements.get("ME_DATA_MB")

        labels = require(plan, "labels", list, context, "plan.labels")
        label_titles = [
            label.get("title") for label in labels
            if isinstance(label, dict) and isinstance(label.get("title"), str)
        ]

        upfront = price.get("payTodayPrice")

        return MobileOffer(
            observed_at=observed_at,
            competitor=self.competitor,
            source_url=url,
            offer_type="SIM Only",
            offer_id=code,
            offer_name=require(plan, "name", str, context, "plan.name"),
            # Plans without a data entitlement (e.g. calls-and-texts-only
            # teen plans) are left as unknown rather than recorded as 0GB
            data_allowance_gb=(
                data_mb / 1000 if data_mb is not None and data_mb >= 0 else None
            ),
            unlimited_data=data_mb == -1,
            contract_term_months=require(
                price, "subscriptionTermInMonths", int,
                context, "plan.price.subscriptionTermInMonths"
            ),
            # payMonthlyPrice already includes any discount, and EE's future
            # prices step up from it, so it's the contract's monthly price.
            # wasPayMonthlyPrice is the pre-discount price, kept in raw_text
            monthly_price=to_decimal(require(
                price, "payMonthlyPrice", (int, float),
                context, "plan.price.payMonthlyPrice"
            )),
            upfront_price=(
                to_decimal(require(
                    price, "payTodayPrice", (int, float),
                    context, "plan.price.payTodayPrice"
                ))
                if upfront is not None else None
            ),
            minutes=allowance_text(entitlements.get("ME_PHONE_MIN")),
            texts=allowance_text(entitlements.get("ME_SMS_TEXTS")),
            promotion_text=" | ".join(label_titles) or None,
            raw_text=json.dumps(combination)
        )


def parse_entitlements(plan: dict, context: str) -> dict[str, int]:
    entitlements = require(
        plan, "entitlements", list, context, "plan.entitlements"
    )

    parsed = {}
    for entitlement in entitlements:
        if not isinstance(entitlement, dict):
            raise OfferParseError(f"{context}: entitlement is not an object")

        code = require(
            entitlement, "code", str, context, "plan.entitlements[].code"
        )
        quantity = require(
            entitlement, "quantity", int,
            context, f"plan.entitlements[{code}].quantity"
        )

        # -1 means unlimited; any other negative value is unexpected
        if quantity < -1:
            raise OfferParseError(
                f"{context}: unexpected {code} quantity {quantity}"
            )

        parsed[code] = quantity

    return parsed


def allowance_text(quantity: int | None) -> str | None:
    if quantity is None:
        return None
    return "Unlimited" if quantity == -1 else str(quantity)
