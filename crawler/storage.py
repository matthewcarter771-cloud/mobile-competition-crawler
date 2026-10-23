import json
from pathlib import Path

from google.cloud import bigquery

from crawler.models import MobileOffer

# Shared with deploy/deploy.sh, which creates the table from the same file
SCHEMA_PATH = Path(__file__).parent / "bigquery_schema.json"


def load_schema() -> list[bigquery.SchemaField]:
    return [
        bigquery.SchemaField.from_api_repr(field)
        for field in json.loads(SCHEMA_PATH.read_text())
    ]


def to_row(offer: MobileOffer) -> dict:
    # mode="json" turns Decimal into a string (exact for NUMERIC),
    # datetime into ISO 8601 and HttpUrl into a plain string
    return offer.model_dump(mode="json")


def write_offers(
    offers: list[MobileOffer],
    table_id: str,
    client: bigquery.Client | None = None
) -> int:
    # A load job rather than streaming inserts: it's free, and it's
    # all-or-nothing, so a failed run never leaves half its rows behind
    client = client or bigquery.Client()

    job_config = bigquery.LoadJobConfig(
        schema=load_schema(),
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        # The table is created by deploy/deploy.sh, and the job's service
        # account can only write to it, not create tables
        create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
    )

    job = client.load_table_from_json(
        [to_row(offer) for offer in offers],
        table_id,
        job_config=job_config
    )
    job.result()

    return job.output_rows
