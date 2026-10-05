from __future__ import annotations

from pathlib import Path

from fry14_engine.aggregation.gateway import AggregationGateway
from fry14_engine.common.enums import IngestionChannel
from fry14_engine.common.ids import new_pipeline_run_id
from fry14_engine.common.metadata import MetadataStamper
from fry14_engine.contracts.registry import ContractRegistry
from fry14_engine.contracts.validation_gateway import ValidationGateway
from fry14_engine.db import bootstrap, get_connection
from fry14_engine.ingestion.models import RawLoanRecord
from fry14_engine.ingestion.stamped import StampedRecord
from fry14_engine.pii.governed_store import GovernedStore
from fry14_engine.pii.hashing_service import PIIHashingService
from fry14_engine.risk_engine.gateway import RiskCalculationGateway
from fry14_engine.synthetic.generator import generate_loan_records

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_HASH_KEY = "aggregation-gateway-test-key"


def _risk_run_from_synthetic(con, count, seed, reporting_period, fixed_clock):
    registry = ContractRegistry(REPO_ROOT / "config" / "contracts")
    contract = registry.get_active("commercial_loan")

    raw = generate_loan_records(count=count, bad_record_rate=0.0, seed=seed)
    ingest_run_id = new_pipeline_run_id()
    stamper = MetadataStamper(
        pipeline_run_id=ingest_run_id,
        source_entity_code="ENTITY_001",
        source_system_of_record="CORE_LOAN_SYSTEM",
        ingestion_channel=IngestionChannel.BATCH,
        clock=fixed_clock,
    )
    stamped = [
        StampedRecord(record=RawLoanRecord.model_validate(r), metadata=stamper.build_metadata())
        for r in raw
    ]

    validation_gateway = ValidationGateway(con, PIIHashingService(TEST_HASH_KEY))
    validation_gateway.run(stamped, contract, ingest_run_id)

    governed_records = GovernedStore(con).read_by_pipeline_run_id(ingest_run_id)
    risk_run_id = new_pipeline_run_id()
    RiskCalculationGateway(con).run(governed_records, reporting_period, risk_run_id)
    return risk_run_id


def test_aggregation_reconciles_with_underlying_metrics(tmp_db_path: Path, fixed_clock):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)

    risk_run_id = _risk_run_from_synthetic(
        con, count=20, seed=21, reporting_period="2026-06", fixed_clock=fixed_clock
    )

    result = AggregationGateway(con).run(risk_run_id)

    assert result.input_metric_count == 20
    assert sum(row.loan_count for row in result.aggregates) == 20

    total_ead_from_metrics = con.execute(
        "SELECT SUM(ead) FROM metrics.loan_risk_metrics WHERE pipeline_run_id = ?", [risk_run_id]
    ).fetchone()[0]
    total_ead_from_aggregates = con.execute(
        "SELECT SUM(total_ead) FROM aggregates.schedule_aggregate WHERE pipeline_run_id = ?",
        [risk_run_id],
    ).fetchone()[0]
    assert total_ead_from_metrics == total_ead_from_aggregates
    con.close()


def test_rerunning_aggregation_for_same_run_does_not_double_count(tmp_db_path: Path, fixed_clock):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)

    risk_run_id = _risk_run_from_synthetic(
        con, count=15, seed=22, reporting_period="2026-06", fixed_clock=fixed_clock
    )

    gateway = AggregationGateway(con)
    first = gateway.run(risk_run_id)
    second = gateway.run(risk_run_id)  # idempotent re-run, same inputs

    assert first.aggregates == second.aggregates

    total_ead = con.execute(
        "SELECT SUM(total_ead) FROM aggregates.schedule_aggregate WHERE pipeline_run_id = ?",
        [risk_run_id],
    ).fetchone()[0]
    expected_total = sum(
        (row.total_ead for row in first.aggregates), start=first.aggregates[0].total_ead * 0
    )
    assert total_ead == expected_total  # not double-counted despite two runs

    row_count = con.execute(
        "SELECT COUNT(*) FROM aggregates.schedule_aggregate WHERE pipeline_run_id = ?",
        [risk_run_id],
    ).fetchone()[0]
    assert row_count == len(first.aggregates)  # upsert, not duplicate rows
    con.close()


def test_new_schema_version_retains_prior_version_as_history(tmp_db_path: Path, fixed_clock):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)

    risk_run_id = _risk_run_from_synthetic(
        con, count=10, seed=23, reporting_period="2026-06", fixed_clock=fixed_clock
    )

    gateway = AggregationGateway(con)
    gateway.run(risk_run_id, schema_version="1.0.0")
    gateway.run(risk_run_id, schema_version="2.0.0")

    version_count = con.execute(
        "SELECT COUNT(DISTINCT schema_version) FROM aggregates.schedule_aggregate "
        "WHERE pipeline_run_id = ?",
        [risk_run_id],
    ).fetchone()[0]
    assert version_count == 2  # both versions retained, not overwritten
    con.close()


def test_read_by_reporting_period_returns_only_matching_rows(tmp_db_path: Path, fixed_clock):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)

    risk_run_id = _risk_run_from_synthetic(
        con, count=10, seed=24, reporting_period="2026-06", fixed_clock=fixed_clock
    )
    AggregationGateway(con).run(risk_run_id)

    from fry14_engine.aggregation.store import AggregationStore

    rows = AggregationStore(con).read_by_reporting_period("2026-06", "1.0.0")
    assert rows
    assert all(row.reporting_period == "2026-06" for row in rows)

    empty = AggregationStore(con).read_by_reporting_period("2099-01", "1.0.0")
    assert empty == []
    con.close()
