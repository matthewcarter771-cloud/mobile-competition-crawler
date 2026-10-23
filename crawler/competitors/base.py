from abc import ABC, abstractmethod
from datetime import datetime
from playwright.async_api import Page

from crawler.models import MobileOffer


class OfferParseError(Exception):
    """A competitor's source data doesn't have the shape the crawler expects."""


class BaseCompetitionCrawler(ABC):

    competitor: str

    @abstractmethod
    async def discover_offer_urls(self, page: Page) -> list[str]:
        pass

    @abstractmethod
    async def extract_offers(
            self,
            page: Page,
            url: str
    ) -> list[MobileOffer]:
        pass

    @abstractmethod
    def parse_record(
            self,
            record: dict,
            url: str,
            observed_at: datetime
    ) -> MobileOffer:
        """Turn one raw API record (as stored in raw_text) into an offer."""
        pass