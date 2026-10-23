from crawler.competitors.ee import EECrawler
from crawler.competitors.three import ThreeCrawler
from crawler.competitors.vodafone import VodafoneCrawler

# Every competitor crawled on each run, in order
CRAWLERS = [ThreeCrawler, VodafoneCrawler, EECrawler]

CRAWLERS_BY_COMPETITOR = {crawler.competitor: crawler for crawler in CRAWLERS}
