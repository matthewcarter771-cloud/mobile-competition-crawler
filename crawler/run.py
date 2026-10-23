import asyncio
import os
import sys
import traceback

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from crawler.competitors.base import OfferParseError
from crawler.competitors.ee import EECrawler
from crawler.competitors.three import ThreeCrawler
from crawler.competitors.vodafone import VodafoneCrawler

CRAWLERS = [ThreeCrawler, VodafoneCrawler, EECrawler]

# Set BQ_TABLE (project.dataset.table) to write results to BigQuery;
# without it the run only prints what it found
BQ_TABLE = os.environ.get("BQ_TABLE")

# Headless by default so it runs in Cloud Run; HEADLESS=false to watch locally
HEADLESS = os.environ.get("HEADLESS", "true").lower() != "false"


async def crawl():
    all_offers = []
    failed_urls = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)

        for crawler_class in CRAWLERS:
            crawler = crawler_class()

            # A fresh context per competitor so cookies and sessions from
            # one site never affect another
            context = await browser.new_context()
            page = await context.new_page()

            urls = await crawler.discover_offer_urls(page)

            for url in urls:
                print(f"Crawling {crawler.competitor}: {url}")

                try:
                    offers = await crawler.extract_offers(page, url)
                except PlaywrightTimeoutError as e:
                    print(f"Timed out crawling {url}, skipping: {e}")
                    failed_urls.append(url)
                    continue
                except OfferParseError as e:
                    print(f"Unexpected data crawling {url}, skipping: {e}")
                    failed_urls.append(url)
                    continue
                except Exception:
                    # Anything else (e.g. an HTTP error from the API) must
                    # not stop the other competitors being crawled
                    print(f"Error crawling {url}, skipping:")
                    traceback.print_exc()
                    failed_urls.append(url)
                    continue

                print(f"\nExtracted {len(offers)} offers from {url}\n")

                # raw_text holds the full API JSON, too long to print
                for offer in offers:
                    print(offer.model_dump(exclude={"raw_text"}))

                all_offers.extend(offers)

            await context.close()

        await browser.close()

    return all_offers, failed_urls


def main() -> int:
    offers, failed_urls = asyncio.run(crawl())

    if offers and BQ_TABLE:
        # Imported here so local runs without BQ_TABLE don't need GCP auth
        from crawler.storage import write_offers

        written = write_offers(offers, BQ_TABLE)
        print(f"Wrote {written} offers to {BQ_TABLE}")

    # Exit non-zero so the scheduler marks the run as failed, while still
    # keeping whatever offers the other URLs produced
    if failed_urls:
        print(f"Failed to crawl {len(failed_urls)} URL(s): {failed_urls}")
        return 1

    if not offers:
        print("No offers found")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
