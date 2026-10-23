from abc import ABC, abstractmethod
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