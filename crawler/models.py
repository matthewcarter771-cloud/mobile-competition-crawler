from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pydantic import BaseModel, HttpUrl, computed_field, model_validator


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

    @model_validator(mode="after")
    def check_term_and_discount(self):
        term = self.contract_term_months

        if term is not None and term < 1:
            raise ValueError(f"contract_term_months must be at least 1, got {term}")

        if (
            self.discount_months is not None
            and term is not None
            and not 1 <= self.discount_months <= term
        ):
            raise ValueError(
                f"discount_months {self.discount_months} must be between "
                f"1 and contract_term_months {term}"
            )

        return self

    # Derived from the prices above, so every competitor uses the same
    # formula and the totals can't disagree with the prices they come from

    @computed_field
    @property
    def total_contract_price(self) -> Decimal | None:
        """Total paid over the contract at sign-up prices.

        The discounted monthly_price for discount_months, then
        list_monthly_price for the rest of the term. Excludes mid-contract
        price rises (e.g. each April), which depend on the start date.
        None when the discount's length is unknown.
        """
        term = self.contract_term_months
        if (
            term is None
            or self.monthly_price is None
            or self.list_monthly_price is None
        ):
            return None

        if self.discount_months is None:
            if self.monthly_price != self.list_monthly_price:
                # Discounted, but for an unknown number of months
                return None
            return self.list_monthly_price * term

        return (
            self.monthly_price * self.discount_months
            + self.list_monthly_price * (term - self.discount_months)
        )

    @computed_field
    @property
    def average_monthly_price(self) -> Decimal | None:
        """total_contract_price spread evenly over the term, to the penny."""
        total = self.total_contract_price
        if total is None:
            return None

        return (total / self.contract_term_months).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
