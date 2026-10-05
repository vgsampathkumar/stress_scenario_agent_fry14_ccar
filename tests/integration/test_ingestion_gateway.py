from __future__ import annotations

from pathlib import Path

from fry14_engine.common.enums import IngestionChannel
from fry14_engine.common.ids import new_pipeline_run_id
from fry14_engine.common.metadata import MetadataStamper
from fry14_engine.db import bootstrap, get_connection
from fry14_engine.ingestion.batch_file_adapter import BatchFileAdapter
from fry14_engine.ingestion.event_stream_adapter import EventStreamAdapter, InMemoryEventSource
from fry14_engine.ingestion.gateway import IngestionGateway
from fry14_engine.synthetic.generator import generate_loan_records
from fry14_engine.synthetic.writers import write_csv


def test_batch_ingestion_lands_all_records_with_complete_metadata(
    tmp_db_path: Path, tmp_path: Path, fixed_clock
):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)

    records = generate_loan_records(count=25, bad_record_rate=0.2, seed=5)
    file_path = tmp_path / "loan_extract.csv"
    write_csv(records, file_path)

    run_id = new_pipeline_run_id()
    adapter = BatchFileAdapter(file_path, source_system_of_record="CORE_LOAN_SYSTEM")
    stamper = MetadataStamper(
        pipeline_run_id=run_id,
        source_entity_code="ENTITY_001",
        source_system_of_record="CORE_LOAN_SYSTEM",
        ingestion_channel=IngestionChannel.BATCH,
        clock=fixed_clock,
    )
    gateway = IngestionGateway(con)

    result = gateway.run(adapter, stamper)

    assert result.records_landed == 25
    assert result.parse_errors == []
    assert result.pipeline_run_id == run_id

    rows = con.execute(
        """
        SELECT pipeline_run_id, source_entity_code, ingestion_channel,
               ingestion_timestamp, loan_id
        FROM landing.raw_loan_record
        WHERE pipeline_run_id = ?
        """,
        [run_id],
    ).fetchall()
    con.close()

    assert len(rows) == 25
    for row in rows:
        pipeline_run_id, source_entity_code, ingestion_channel, ingestion_timestamp, loan_id = row
        assert pipeline_run_id == run_id
        assert source_entity_code == "ENTITY_001"
        assert ingestion_channel == "BATCH"
        assert ingestion_timestamp is not None
        assert loan_id is not None


def test_event_ingestion_lands_records_with_event_channel(tmp_db_path: Path, fixed_clock):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)

    source = InMemoryEventSource()
    for record in generate_loan_records(count=8, seed=6):
        source.publish(record)

    run_id = new_pipeline_run_id()
    adapter = EventStreamAdapter(source, source_system_of_record="CREDIT_PERFORMANCE_FEED")
    stamper = MetadataStamper(
        pipeline_run_id=run_id,
        source_entity_code="ENTITY_001",
        source_system_of_record="CREDIT_PERFORMANCE_FEED",
        ingestion_channel=IngestionChannel.EVENT,
        clock=fixed_clock,
    )
    gateway = IngestionGateway(con)

    result = gateway.run(adapter, stamper)

    assert result.records_landed == 8

    channel = con.execute(
        "SELECT DISTINCT ingestion_channel FROM landing.raw_loan_record WHERE pipeline_run_id = ?",
        [run_id],
    ).fetchall()
    con.close()

    assert channel == [("EVENT",)]


def test_bad_business_values_still_land_uninterrupted(
    tmp_db_path: Path, tmp_path: Path, fixed_clock
):
    """Requirement 2.2: pipeline processing must continue uninterrupted for
    valid records — but that's a contract-validation concern (Phase 2).
    Ingestion itself must land *all* type-coercible records, good or bad,
    without pre-emptively filtering anything on business rules."""
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)

    records = generate_loan_records(count=16, bad_record_rate=0.5, seed=13)
    file_path = tmp_path / "loan_extract.csv"
    write_csv(records, file_path)

    run_id = new_pipeline_run_id()
    adapter = BatchFileAdapter(file_path, source_system_of_record="CORE_LOAN_SYSTEM")
    stamper = MetadataStamper(
        pipeline_run_id=run_id,
        source_entity_code="ENTITY_001",
        source_system_of_record="CORE_LOAN_SYSTEM",
        ingestion_channel=IngestionChannel.BATCH,
        clock=fixed_clock,
    )
    gateway = IngestionGateway(con)

    result = gateway.run(adapter, stamper)

    assert result.records_landed == 16  # every record lands, good and bad alike

    negative_balances = con.execute(
        "SELECT COUNT(*) FROM landing.raw_loan_record "
        "WHERE pipeline_run_id = ? AND outstanding_balance < 0",
        [run_id],
    ).fetchone()[0]
    con.close()

    assert negative_balances > 0
