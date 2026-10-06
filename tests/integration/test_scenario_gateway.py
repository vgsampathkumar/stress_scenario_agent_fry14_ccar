"""Stress Scenario Gateway integration tests: builds governed loans and
baseline risk metrics the same way `test_risk_calculation_gateway.py`
does, then runs a full governed scenario end-to-end through
`StressScenarioGateway` with no LLM involved (03-implementation-plan.md
Phase 8). See 02-design-document.md §3.18.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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
from fry14_engine.scenario.gateway import StressScenarioGateway
from fry14_engine.scenario.models import ScenarioName, ScenarioTableNotApprovedError
from fry14_engine.scenario.reference_store import ScenarioReferenceStore
from fry14_engine.scenario.run_store import ScenarioRunStore
from fry14_engine.scenario.spec_models import PortfolioScope
from fry14_engine.scenario.spec_store import ScenarioSpecStore
from fry14_engine.scenario.spec_validator import build_scenario_spec
from fry14_engine.synthetic.generator import generate_loan_records

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_HASH_KEY = "scenario-gateway-test-key"


def _baseline_run(con, count, seed, fixed_clock):
    registry = ContractRegistry(REPO_ROOT / "config" / "contracts")
    contract = registry.get_active("commercial_loan")

    raw = generate_loan_records(count=count, bad_record_rate=0.0, seed=seed)
    base_pipeline_run_id = new_pipeline_run_id()
    stamper = MetadataStamper(
        pipeline_run_id=base_pipeline_run_id,
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
    validation_gateway.run(stamped, contract, base_pipeline_run_id)

    governed_records = GovernedStore(con).read_by_pipeline_run_id(base_pipeline_run_id)
    RiskCalculationGateway(con).run(
        governed_records, reporting_period="2026-06", pipeline_run_id=base_pipeline_run_id
    )
    return base_pipeline_run_id, governed_records


@pytest.fixture
def connection(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    yield con
    con.close()


def test_scenario_gateway_persists_full_run(connection, fixed_clock):
    base_pipeline_run_id, governed_records = _baseline_run(
        connection, count=15, seed=21, fixed_clock=fixed_clock
    )
    assert governed_records

    reference_store = ScenarioReferenceStore(connection)
    spec = build_scenario_spec(
        reference_store,
        requested_by="risk.analyst@example.com",
        portfolio_scope=PortfolioScope(reporting_period="2026-06"),
        translation_table_version="1.0.0",
        regulatory_parameter_version="1.0.0",
        base_scenario=ScenarioName.SEVERELY_ADVERSE,
        supervisory_scenario_version="FED-2026",
    )

    gateway = StressScenarioGateway(connection)
    result = gateway.run(spec, base_pipeline_run_id)

    assert len(result.stressed_loan_metrics) == len(governed_records) * spec.horizon_quarters
    assert result.comparison_rows
    assert result.projected_loss_9q > 0

    spec_row_count = connection.execute(
        "SELECT COUNT(*) FROM scenario.scenario_spec WHERE scenario_spec_id = ?",
        [spec.scenario_spec_id],
    ).fetchone()[0]
    assert spec_row_count == 1

    run_row_count = connection.execute(
        "SELECT COUNT(*) FROM scenario.scenario_run_result WHERE scenario_run_id = ?",
        [result.scenario_run_id],
    ).fetchone()[0]
    assert run_row_count == 1

    metrics_row_count = connection.execute(
        "SELECT COUNT(*) FROM scenario.stressed_loan_metrics WHERE scenario_run_id = ?",
        [result.scenario_run_id],
    ).fetchone()[0]
    assert metrics_row_count == len(result.stressed_loan_metrics)

    comparison_row_count = connection.execute(
        "SELECT COUNT(*) FROM scenario.scenario_comparison WHERE scenario_run_id = ?",
        [result.scenario_run_id],
    ).fetchone()[0]
    assert comparison_row_count == len(result.comparison_rows)

    audit_event_count = connection.execute(
        "SELECT COUNT(*) FROM audit.event_log WHERE event_type = 'STRESS_SCENARIO' "
        "AND pipeline_run_id = ?",
        [base_pipeline_run_id],
    ).fetchone()[0]
    assert audit_event_count == 2  # spec_persisted + run_persisted


def test_scenario_gateway_read_back_matches_persisted_result(connection, fixed_clock):
    base_pipeline_run_id, governed_records = _baseline_run(
        connection, count=5, seed=22, fixed_clock=fixed_clock
    )

    reference_store = ScenarioReferenceStore(connection)
    spec = build_scenario_spec(
        reference_store,
        requested_by="risk.analyst@example.com",
        portfolio_scope=PortfolioScope(reporting_period="2026-06"),
        translation_table_version="1.0.0",
        regulatory_parameter_version="1.0.0",
        base_scenario=ScenarioName.SEVERELY_ADVERSE,
        supervisory_scenario_version="FED-2026",
    )

    gateway = StressScenarioGateway(connection)
    result = gateway.run(spec, base_pipeline_run_id)

    read_back_spec = ScenarioSpecStore(connection).read(spec.scenario_spec_id)
    assert read_back_spec == spec

    run_store = ScenarioRunStore(connection)
    read_back_result = run_store.read_result(result.scenario_run_id)
    assert read_back_result.input_hash == result.input_hash
    assert read_back_result.projected_loss_9q == result.projected_loss_9q
    assert len(read_back_result.stressed_loan_metrics) == len(result.stressed_loan_metrics)
    assert len(read_back_result.comparison_rows) == len(result.comparison_rows)


def test_unapproved_translation_table_rejected_before_any_run(connection, fixed_clock):
    base_pipeline_run_id, _ = _baseline_run(connection, count=5, seed=23, fixed_clock=fixed_clock)

    connection.execute(
        "INSERT INTO scenario.scenario_translation_table "
        "(version, effective_date, status, multiplier_floor, multiplier_cap) "
        "VALUES ('2.0.0-draft', DATE '2026-02-01', 'DRAFT', 0.5, 5.0)"
    )
    reference_store = ScenarioReferenceStore(connection)

    with pytest.raises(ScenarioTableNotApprovedError):
        build_scenario_spec(
            reference_store,
            requested_by="risk.analyst@example.com",
            portfolio_scope=PortfolioScope(reporting_period="2026-06"),
            translation_table_version="2.0.0-draft",
            regulatory_parameter_version="1.0.0",
        )

    # Nothing should have been persisted — the gateway's run() is never reached.
    spec_count = connection.execute(
        "SELECT COUNT(*) FROM scenario.scenario_spec WHERE translation_table_version = ?",
        ["2.0.0-draft"],
    ).fetchone()[0]
    assert spec_count == 0
