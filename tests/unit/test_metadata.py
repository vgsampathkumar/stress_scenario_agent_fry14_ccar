from __future__ import annotations

from fry14_engine.common.enums import IngestionChannel
from fry14_engine.common.ids import new_pipeline_run_id, new_record_id
from fry14_engine.common.metadata import IngestionMetadata, MetadataStamper


def test_new_pipeline_run_id_is_unique():
    assert new_pipeline_run_id() != new_pipeline_run_id()


def test_new_record_id_is_unique():
    assert new_record_id() != new_record_id()


def test_stamp_adds_complete_ingestion_metadata(fixed_clock):
    run_id = new_pipeline_run_id()
    stamper = MetadataStamper(
        pipeline_run_id=run_id,
        source_entity_code="ENTITY_001",
        source_system_of_record="CORE_LOAN_SYSTEM",
        ingestion_channel=IngestionChannel.BATCH,
        clock=fixed_clock,
    )
    record = {"loan_id": "L-1"}

    stamped = stamper.stamp(record)

    assert stamped["loan_id"] == "L-1"
    meta = stamped["_ingestion_metadata"]
    assert meta["pipeline_run_id"] == run_id
    assert meta["source_entity_code"] == "ENTITY_001"
    assert meta["source_system_of_record"] == "CORE_LOAN_SYSTEM"
    assert meta["ingestion_channel"] == "BATCH"
    assert meta["ingestion_timestamp"].startswith("2026-01-15T12:00:00")


def test_stamp_does_not_mutate_input_record(fixed_clock):
    stamper = MetadataStamper(
        pipeline_run_id=new_pipeline_run_id(),
        source_entity_code="ENTITY_001",
        source_system_of_record="CORE_LOAN_SYSTEM",
        ingestion_channel=IngestionChannel.EVENT,
        clock=fixed_clock,
    )
    record = {"loan_id": "L-2"}

    stamper.stamp(record)

    assert "_ingestion_metadata" not in record


def test_stamp_many_shares_one_pipeline_run_id(fixed_clock):
    run_id = new_pipeline_run_id()
    stamper = MetadataStamper(
        pipeline_run_id=run_id,
        source_entity_code="ENTITY_001",
        source_system_of_record="CORE_LOAN_SYSTEM",
        ingestion_channel=IngestionChannel.BATCH,
        clock=fixed_clock,
    )
    records = [{"loan_id": "L-1"}, {"loan_id": "L-2"}, {"loan_id": "L-3"}]

    stamped = stamper.stamp_many(records)

    assert len(stamped) == 3
    run_ids = {r["_ingestion_metadata"]["pipeline_run_id"] for r in stamped}
    assert run_ids == {run_id}


def test_ingestion_metadata_rejects_blank_source_entity_code():
    import pytest as _pytest
    from pydantic import ValidationError

    with _pytest.raises(ValidationError):
        IngestionMetadata(
            ingestion_timestamp="2026-01-15T12:00:00+00:00",
            source_entity_code="",
            pipeline_run_id="run-1",
            source_system_of_record="CORE",
            ingestion_channel=IngestionChannel.BATCH,
        )
