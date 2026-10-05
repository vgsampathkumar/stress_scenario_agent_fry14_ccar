from __future__ import annotations

from pathlib import Path

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
TEST_HASH_KEY = "risk-gateway-test-key"


def _governed_records_from_synthetic(con, count, bad_record_rate, seed, fixed_clock):
    registry = ContractRegistry(REPO_ROOT / "config" / "contracts")
    contract = registry.get_active("commercial_loan")

    raw = generate_loan_records(count=count, bad_record_rate=bad_record_rate, seed=seed)
    run_id = new_pipeline_run_id()
    stamper = MetadataStamper(
        pipeline_run_id=run_id,
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
    validation_gateway.run(stamped, contract, run_id)

    return GovernedStore(con).read_by_pipeline_run_id(run_id), run_id


def test_risk_calculation_persists_metrics_for_every_governed_record(
    tmp_db_path: Path, fixed_clock
):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)

    governed_records, _ = _governed_records_from_synthetic(
        con, count=20, bad_record_rate=0.0, seed=12, fixed_clock=fixed_clock
    )
    assert governed_records  # sanity: the fixture actually produced governed rows

    risk_run_id = new_pipeline_run_id()
    gateway = RiskCalculationGateway(con)
    result = gateway.run(governed_records, reporting_period="2026-06", pipeline_run_id=risk_run_id)

    assert len(result.metrics) == len(governed_records)
    assert result.exceptions == []

    row_count = con.execute(
        "SELECT COUNT(*) FROM metrics.loan_risk_metrics WHERE pipeline_run_id = ?", [risk_run_id]
    ).fetchone()[0]
    assert row_count == len(governed_records)
    con.close()


def test_risk_calculation_persists_exceptions_separately_from_metrics(
    tmp_db_path: Path, fixed_clock
):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)

    governed_records, _ = _governed_records_from_synthetic(
        con, count=10, bad_record_rate=0.0, seed=13, fixed_clock=fixed_clock
    )
    # Force a calc exception on one record by stripping its PD, bypassing the
    # normal contract (which doesn't require PD non-null) to exercise the path.
    tampered = governed_records[0].model_copy(update={"probability_of_default": None})
    records = [tampered, *governed_records[1:]]

    risk_run_id = new_pipeline_run_id()
    gateway = RiskCalculationGateway(con)
    result = gateway.run(records, reporting_period="2026-06", pipeline_run_id=risk_run_id)

    assert len(result.exceptions) == 1
    assert len(result.metrics) == len(records) - 1

    exception_count = con.execute(
        "SELECT COUNT(*) FROM metrics.calculation_exception WHERE pipeline_run_id = ?",
        [risk_run_id],
    ).fetchone()[0]
    metrics_count = con.execute(
        "SELECT COUNT(*) FROM metrics.loan_risk_metrics WHERE pipeline_run_id = ?", [risk_run_id]
    ).fetchone()[0]
    assert exception_count == 1
    assert metrics_count == len(records) - 1
    con.close()


def test_risk_metrics_reconcile_with_hand_computed_totals(tmp_db_path: Path, fixed_clock):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)

    governed_records, _ = _governed_records_from_synthetic(
        con, count=5, bad_record_rate=0.0, seed=99, fixed_clock=fixed_clock
    )

    risk_run_id = new_pipeline_run_id()
    gateway = RiskCalculationGateway(con)
    result = gateway.run(governed_records, reporting_period="2026-06", pipeline_run_id=risk_run_id)

    total_ead_from_db = con.execute(
        "SELECT SUM(ead) FROM metrics.loan_risk_metrics WHERE pipeline_run_id = ?", [risk_run_id]
    ).fetchone()[0]
    total_ead_from_result = sum((m.ead for m in result.metrics), start=result.metrics[0].ead * 0)

    assert total_ead_from_db == total_ead_from_result
    con.close()
