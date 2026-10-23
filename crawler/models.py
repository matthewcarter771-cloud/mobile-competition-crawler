from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, HttpUrl


class MobileOffer (BaseModel):
    observed_at: datetime

    competitor: str
    source_url: HttpUrl

    offer_type: str
    # The competitor's own ID for the offer, stable across crawls
    offer_id: str | None = None
    offer_name: str | None = None
    # The competitor's own plan family or tier, e.g. Three "Lite", EE "TEEN",
    # Vodafone "BASICS_PLAN". Labels aren't comparable across competitors
    plan_tier: str | None = None

    # None when the data is unlimited, or when the competitor doesn't give
    # an amount (e.g. EE's speed-capped Protected Plan)
    data_allowance_gb: float | None = None
    unlimited_data: bool = False

    contract_term_months: int | None = None

    # Prices include VAT. monthly_price is what the customer pays per month
    # at sign-up, after any automatic discount (but not discount codes).
    # list_monthly_price is the price without that discount; the two are
    # equal when there's no discount
    monthly_price: Decimal | None = None
    list_monthly_price: Decimal | None = None
    # How many months monthly_price lasts before reverting to
    # list_monthly_price: the contract term for whole-contract discounts,
    # None when there's no discount or its length isn't known
    discount_months: int | None = None

    minutes: str | None = None
    texts: str | None = None

    # The competitor's promotion label as shown, plus what can be parsed
    # out of it
    promotion_text: str | None = None
    promotion_code: str | None = None
    promotion_ends_on: date | None = None

    raw_text: str | None = None
