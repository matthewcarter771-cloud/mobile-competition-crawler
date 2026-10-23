from datetime import datetime
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

    data_allowance_gb: float | None = None
    unlimited_data: bool = False

    contract_term_months: int | None = None

    monthly_price: Decimal | None = None
    introductory_price: Decimal | None = None
    introductory_months: int | None = None
    upfront_price: Decimal | None = None

    minutes: str | None = None
    texts: str | None = None

    promotion_text: str | None = None

    handset_manufacturer: str | None = None
    handset_model: str | None = None
    handset_storage_gb: int | None = None

    raw_text: str | None = None