import json
from datetime import datetime, timezone
from decimal import Decimal

from google.cloud import bigquery

from crawler.models import MobileOffer
from crawler.storage import SCHEMA_PATH, load_schema, to_row, write_offers


def make_offer(**overrides):
    fields = dict(
        observed_at=datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc),
        competitor="Three",
        source_url="https://www.three.co.uk/shop/sim-only/pay-monthly",
        offer_type="SIM Only",
        offer_id="1467471_1465711_1455891",
        offer_name="120GB Lite SIMO 24M",
        data_allowance_gb=120.0,
        contract_term_months=24,
        monthly_price=Decimal("16.0"),
        introductory_price=Decimal("10.5"),
        introductory_months=6,
        raw_text='{"id": "1467471_1465711_1455891"}',
    )
    fields.update(overrides)
    return MobileOffer(**fields)


def test_schema_matches_model_fields():
    # Adding a field to MobileOffer without adding it to the BigQuery
    # schema would make every load job fail
    schema_names = [field.name for field in load_schema()]

    assert schema_names == list(MobileOffer.model_fields)


def test_required_schema_fields_are_required_in_model():
    required = {
        field["name"]
        for field in json.loads(SCHEMA_PATH.read_text())
        if field["mode"] == "REQUIRED"
    }
    model_optional = {
        name for name, field in MobileOffer.model_fields.items()
        if not field.is_required() and field.default is None
    }

    assert not required & model_optional


def test_row_is_json_serialisable_with_exact_prices():
    row = to_row(make_offer())

    assert json.loads(json.dumps(row)) == row
    assert row["monthly_price"] == "16.0"
    assert row["introductory_price"] == "10.5"
    assert row["observed_at"] == "2026-10-23T12:00:00Z"
    assert row["source_url"] == "https://www.three.co.uk/shop/sim-only/pay-monthly"
    assert row["upfront_price"] is None


class FakeLoadJob:
    def __init__(self, rows):
        self.output_rows = len(rows)
        self.waited = False

    def result(self):
        self.waited = True


class FakeClient:
    def __init__(self):
        self.calls = []

    def load_table_from_json(self, rows, table_id, job_config):
        self.job = FakeLoadJob(rows)
        self.calls.append((rows, table_id, job_config))
        return self.job


def test_write_offers_appends_with_load_job():
    client = FakeClient()
    offers = [make_offer(), make_offer(offer_id="other")]

    written = write_offers(offers, "proj.dataset.table", client=client)

    rows, table_id, job_config = client.calls[0]
    assert written == 2
    assert client.job.waited
    assert table_id == "proj.dataset.table"
    assert [r["offer_id"] for r in rows] == ["1467471_1465711_1455891", "other"]
    assert job_config.write_disposition == bigquery.WriteDisposition.WRITE_APPEND
    assert job_config.create_disposition == bigquery.CreateDisposition.CREATE_NEVER
    assert job_config.source_format == bigquery.SourceFormat.NEWLINE_DELIMITED_JSON
    assert job_config.schema == load_schema()
