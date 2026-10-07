"""MCP Tool Server (C23) integration tests: a handful of tools run
end-to-end through policy enforcement, trace logging, and the real
underlying gateways — no LLM/agent involved yet (that's Phase 10). See
02-design-document.md §3.13.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from fry14_engine.agent_trace.logger import AgentTraceLogger
from fry14_engine.common.enums import AgentId, IngestionChannel, RoleName
from fry14_engine.common.ids import new_pipeline_run_id
from fry14_engine.common.metadata import MetadataStamper
from fry14_engine.contracts.registry import ContractRegistry
from fry14_engine.db import bootstrap, get_connection
from fry14_engine.ingestion.adapter import IngestionAdapter, IngestionBatch
from fry14_engine.mcp_server.models import ToolContext
from fry14_engine.mcp_server.server import McpToolServer
from fry14_engine.pii.governed_store import GovernedStore
from fry14_engine.pii.hashing_service import PIIHashingService
from fry14_engine.policy.models import PolicyOutcome
from fry14_engine.scenario.models import ScenarioName
from fry14_engine.scenario.spec_models import PortfolioScope
from fry14_engine.synthetic.generator import generate_loan_records

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_HASH_KEY = "mcp-server-test-key"


class _FakeAdapter(IngestionAdapter):
    channel = IngestionChannel.BATCH
    source_system_of_record = "TEST_SOURCE"

    def __init__(self, records: list[dict]) -> None:
        self._records = records

    def read(self) -> IngestionBatch:
        batch = IngestionBatch()
        for payload in self._records:
            self._normalize_into(payload, batch)
        return batch


@pytest.fixture
def connection(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    yield con
    con.close()


@pytest.fixture
def server(connection) -> McpToolServer:
    return McpToolServer(connection, PIIHashingService(TEST_HASH_KEY))


def _ag1_ctx(session_id: str = "sess-1") -> ToolContext:
    return ToolContext(AgentId.AG1_PIPELINE_OPERATIONS, RoleName.DATA_ENGINEER, session_id, "alice")


def test_ingest_batch_allowed_lands_records(server: McpToolServer):
    adapter = _FakeAdapter(generate_loan_records(count=5, bad_record_rate=0.0, seed=1))
    run_id = new_pipeline_run_id()
    stamper = MetadataStamper(
        pipeline_run_id=run_id,
        source_entity_code="ENTITY_001",
        source_system_of_record="TEST_SOURCE",
        ingestion_channel=IngestionChannel.BATCH,
    )

    result = server.ingest_batch(_ag1_ctx(), adapter, stamper)

    assert result.decision.outcome == PolicyOutcome.ALLOW
    assert result.result.records_landed == 5


def test_ingest_event_allowed_lands_records(server: McpToolServer):
    adapter = _FakeAdapter(generate_loan_records(count=3, bad_record_rate=0.0, seed=2))
    stamper = MetadataStamper(
        pipeline_run_id=new_pipeline_run_id(),
        source_entity_code="ENTITY_001",
        source_system_of_record="TEST_SOURCE",
        ingestion_channel=IngestionChannel.EVENT,
    )

    result = server.ingest_event(_ag1_ctx(), adapter, stamper)

    assert result.decision.outcome == PolicyOutcome.ALLOW
    assert result.result.records_landed == 3


def test_ingest_batch_denied_for_wrong_role(server: McpToolServer):
    adapter = _FakeAdapter([])
    stamper = MetadataStamper(
        pipeline_run_id=new_pipeline_run_id(),
        source_entity_code="ENTITY_001",
        source_system_of_record="TEST_SOURCE",
        ingestion_channel=IngestionChannel.BATCH,
    )
    ctx = ToolContext(AgentId.AG1_PIPELINE_OPERATIONS, RoleName.FINANCE, "sess-1", "alice")

    result = server.ingest_batch(ctx, adapter, stamper)

    assert result.decision.outcome == PolicyOutcome.DENY
    assert result.result is None


def _run_pipeline_through_risk_calc(server: McpToolServer, connection, count=10, seed=7):
    registry = ContractRegistry(REPO_ROOT / "config" / "contracts")
    contract = registry.get_active("commercial_loan")

    raw = generate_loan_records(count=count, bad_record_rate=0.0, seed=seed)
    adapter = _FakeAdapter(raw)
    run_id = new_pipeline_run_id()
    stamper = MetadataStamper(
        pipeline_run_id=run_id,
        source_entity_code="ENTITY_001",
        source_system_of_record="TEST_SOURCE",
        ingestion_channel=IngestionChannel.BATCH,
    )
    ingest_result = server.ingest_batch(_ag1_ctx(), adapter, stamper)
    stamped = ingest_result.result.stamped_records

    validate_result = server.validate_against_contract(_ag1_ctx(), stamped, contract, run_id)
    governed_records = GovernedStore(connection).read_by_pipeline_run_id(run_id)

    calc_result = server.calculate_risk_metrics(_ag1_ctx(), governed_records, "2026-06", run_id)
    agg_result = server.aggregate_schedules(_ag1_ctx(), run_id)
    return run_id, validate_result, calc_result, agg_result


def test_full_pipeline_chain_allowed_for_ag1_data_engineer(server: McpToolServer, connection):
    run_id, validate_result, calc_result, agg_result = _run_pipeline_through_risk_calc(
        server, connection
    )
    assert validate_result.decision.outcome == PolicyOutcome.ALLOW
    assert calc_result.decision.outcome == PolicyOutcome.ALLOW
    assert agg_result.decision.outcome == PolicyOutcome.ALLOW
    assert len(calc_result.result.metrics) == validate_result.result.governed_count


def test_publish_within_threshold_executes_immediately(server: McpToolServer, connection):
    run_id, _validate, _calc, agg_result = _run_pipeline_through_risk_calc(server, connection)
    ctx = ToolContext(
        AgentId.AG1_PIPELINE_OPERATIONS, RoleName.REGULATORY_REPORTING, "sess-1", "carol"
    )

    result = server.publish_data_product(
        ctx,
        data_product_id="dp1",
        pipeline_run_id=run_id,
        dq_pass_percentage=100.0,
        run_completed_at=datetime.datetime.now(datetime.UTC),
        output_schema_version=agg_result.result.schema_version,
        output_schema_effective_date=datetime.date.today(),
    )

    assert result.decision.outcome == PolicyOutcome.ALLOW
    assert result.result is not None


def test_publish_below_threshold_proposes_instead_of_executing(server: McpToolServer, connection):
    run_id, _validate, _calc, agg_result = _run_pipeline_through_risk_calc(server, connection)
    ctx = ToolContext(
        AgentId.AG1_PIPELINE_OPERATIONS, RoleName.REGULATORY_REPORTING, "sess-1", "carol"
    )

    result = server.publish_data_product(
        ctx,
        data_product_id="dp1",
        pipeline_run_id=run_id,
        dq_pass_percentage=50.0,
        run_completed_at=datetime.datetime.now(datetime.UTC),
        output_schema_version=agg_result.result.schema_version,
        output_schema_effective_date=datetime.date.today(),
    )

    assert result.decision.outcome == PolicyOutcome.PROPOSE
    assert result.result is None  # catalog was never touched
    assert (
        connection.execute("SELECT COUNT(*) FROM catalog.data_product_catalog_entry").fetchone()[0]
        == 0
    )

    proposal_row = connection.execute(
        "SELECT proposal_id, requested_by FROM agent_governance.agent_proposal"
    ).fetchone()
    assert proposal_row == (result.decision.proposal_id, "carol")


def test_build_and_run_stress_scenario_requires_confirmation(server: McpToolServer, connection):
    run_id, *_ = _run_pipeline_through_risk_calc(server, connection)
    ctx = ToolContext(AgentId.AG3_STRESS_SCENARIO, RoleName.FINANCE, "sess-2", "dave")

    spec_result = server.build_scenario_spec(
        ctx,
        PortfolioScope(reporting_period="2026-06"),
        "1.0.0",
        "1.0.0",
        base_scenario=ScenarioName.SEVERELY_ADVERSE,
        supervisory_scenario_version="FED-2026",
    )
    assert spec_result.decision.outcome == PolicyOutcome.ALLOW

    unconfirmed = server.run_stress_scenario(ctx, spec_result.result, run_id)
    assert unconfirmed.decision.outcome == PolicyOutcome.CONFIRM_REQUIRED
    assert unconfirmed.result is None

    confirmed = server.run_stress_scenario(ctx, spec_result.result, run_id, already_confirmed=True)
    assert confirmed.decision.outcome == PolicyOutcome.ALLOW
    assert confirmed.result is not None
    assert confirmed.result.stressed_loan_metrics


def test_query_sandbox_denied_for_role_without_permission(server: McpToolServer, connection):
    run_id, *_ = _run_pipeline_through_risk_calc(server, connection)
    ctx = ToolContext(AgentId.AG5_DATA_PRODUCT_CONCIERGE, RoleName.DATA_ENGINEER, "sess-3", "erin")

    result = server.query_sandbox(ctx, "2026-06", "1.0.0")

    assert result.decision.outcome == PolicyOutcome.DENY
    assert result.result is None


def test_query_sandbox_allowed_returns_aggregates(server: McpToolServer, connection):
    run_id, *_ = _run_pipeline_through_risk_calc(server, connection)
    server.aggregate_schedules(_ag1_ctx(), run_id)  # ensure aggregates exist for this period
    ctx = ToolContext(AgentId.AG5_DATA_PRODUCT_CONCIERGE, RoleName.FINANCE, "sess-3", "erin")

    result = server.query_sandbox(ctx, "2026-06", "1.0.0")

    assert result.decision.outcome == PolicyOutcome.ALLOW
    assert result.result


def test_get_lineage_and_catalog_status_available_to_every_agent(server: McpToolServer, connection):
    run_id, *_ = _run_pipeline_through_risk_calc(server, connection)
    for agent_id in AgentId:
        ctx = ToolContext(agent_id, RoleName.DATA_ENGINEER, "sess-4", "alice")
        lineage_result = server.get_lineage(ctx, run_id)
        catalog_result = server.get_catalog_status(ctx, "dp1")
        assert lineage_result.decision.outcome == PolicyOutcome.ALLOW
        assert catalog_result.decision.outcome == PolicyOutcome.ALLOW


def test_every_tool_call_logs_tool_call_and_tool_result_events(server: McpToolServer, connection):
    adapter = _FakeAdapter([])
    stamper = MetadataStamper(
        pipeline_run_id=new_pipeline_run_id(),
        source_entity_code="ENTITY_001",
        source_system_of_record="TEST_SOURCE",
        ingestion_channel=IngestionChannel.BATCH,
    )
    server.ingest_batch(_ag1_ctx("sess-trace"), adapter, stamper)

    events = AgentTraceLogger(connection).read_session("sess-trace")
    event_types = [str(e.event_type) for e in events]
    assert event_types == ["TOOL_CALL", "POLICY_DECISION", "TOOL_RESULT"]
