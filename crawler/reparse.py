"""Rebuild stored offers from their raw_text with the current parsing code.

Every row keeps the competitor's raw API record in raw_text, so when the
parsing logic or schema changes, old rows can be re-derived rather than
left inconsistent with new ones.

Usage:
    python -m crawler.reparse SOURCE_TABLE DEST_TABLE

SOURCE_TABLE is read (any schema with competitor, observed_at, source_url
and raw_text); the rebuilt rows are appended to DEST_TABLE, which must
already exist with the current schema.
"""

import json
import sys

from google.cloud import bigquery

from crawler.models import MobileOffer
from crawler.registry import CRAWLERS_BY_COMPETITOR
from crawler.storage import write_offers


def reparse_row(row) -> MobileOffer:
    crawler = CRAWLERS_BY_COMPETITOR[row["competitor"]]()
    record = json.loads(row["raw_text"])

    return crawler.parse_record(record, row["source_url"], row["observed_at"])


def main(source_table: str, dest_table: str) -> int:
    client = bigquery.Client()

    rows = client.query(
        f"SELECT competitor, observed_at, source_url, raw_text "
        f"FROM `{source_table}`"
    ).result()

    offers = [reparse_row(row) for row in rows]
    print(f"Reparsed {len(offers)} rows from {source_table}")

    written = write_offers(offers, dest_table, client=client)
    print(f"Wrote {written} rows to {dest_table}")

    return 0 if written == len(offers) else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)

    sys.exit(main(sys.argv[1], sys.argv[2]))
