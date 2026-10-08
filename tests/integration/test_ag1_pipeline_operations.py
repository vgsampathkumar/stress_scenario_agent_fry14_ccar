"""AG-1 Pipeline Operations Agent (C18) integration tests: Flow A from
02-design-document.md §4.1 end-to-end through the real MCP-tool-gated
pipeline, plus the DQ-breach-escalates-publish-to-PROPOSE behavior
requirements.md §3.2 (AG-1) describes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fry14_engine.agent_runtime.ag1_pipeline_operations import (
    PipelineOperationsAgent,
    ToolCallDeniedError,
)
from fry14_engine.agent_runtime.runtime import AgentRuntime
from fry14_engine.common.enums import AgentId, IngestionChannel, RoleName
from fry14_engine.contracts.registry import ContractRegistry
from fry14_engine.db import bootstrap, get_connection
from fry14_engine.ingestion.adapter import IngestionAdapter, IngestionBatch
from fry14_engine.mcp_server.server import McpToolServer
from fry14_engine.orchestrator.models import ChannelSource
from fry14_engine.pii.hashing_service import PIIHashingService
from fry14_engine.policy.models import PolicyOutcome
from fry14_engine.synthetic.generator import generate_loan_records

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_HASH_KEY = "ag1-test-key"


class _FakeAdapter(IngestionAdapter):
    channel = IngestionChannel.BATCH
    source_system_of_record = "CORE"

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
def agent(connection) -> PipelineOperationsAgent:
    server = McpToolServer(connection, PIIHashingService(TEST_HASH_KEY))
    runtime = AgentRuntime(connection)
    return PipelineOperationsAgent(connection, server, runtime)


@pytest.fixture
def contract():
    return ContractRegistry(REPO_ROOT / "config" / "contracts").get_active("commercial_loan")


def _channel(count: int, bad_record_rate: float, seed: int) -> ChannelSource:
    records = generate_loan_records(count=count, bad_record_rate=bad_record_rate, seed=seed)
    return ChannelSource(
        adapter=_FakeAdapter(records),
        source_entity_code="ENTITY_001",
        source_system_of_record="CORE",
    )


def test_flow_a_runs_end_to_end_and_publishes_when_dq_is_clean(agent, contract):
    channel = _channel(count=20, bad_record_rate=0.0, seed=1)
    report = agent.run("bob", RoleName.ADMIN, [channel], contract, "2026-06", "dp1")

    assert report.total_count == 20
    assert report.governed_count == 20
    assert report.quarantined_count == 0
    assert report.metrics_computed == 20
    assert report.aggregate_rows > 0
    assert report.dq_pass_percentage == 100.0
    assert report.publish_outcome == str(PolicyOutcome.ALLOW)
    assert not report.triage_handoff_recommended


def test_publish_escalates_to_propose_on_dq_breach(agent, contract):
    # bad_record_rate cycles through 4 defect kinds; ~25% breach is well
    # below the 98% default threshold for any admin-authorized role.
    channel = _channel(count=20, bad_record_rate=0.25, seed=2)
    report = agent.run("bob", RoleName.ADMIN, [channel], contract, "2026-06", "dp1")

    assert report.quarantined_count > 0
    assert report.dq_pass_percentage < 98.0
    assert report.triage_handoff_recommended is True
    assert report.publish_outcome == str(PolicyOutcome.PROPOSE)
    assert report.publish_proposal_id is not None


def test_publish_is_never_executed_once_escalated(agent, contract, connection):
    channel = _channel(count=20, bad_record_rate=0.25, seed=3)
    report = agent.run("bob", RoleName.ADMIN, [channel], contract, "2026-06", "dp1")

    assert report.publish_outcome == str(PolicyOutcome.PROPOSE)
    catalog_count = connection.execute(
        "SELECT COUNT(*) FROM catalog.data_product_catalog_entry WHERE data_product_id = 'dp1'"
    ).fetchone()[0]
    assert catalog_count == 0


def test_separation_of_duties_reports_publish_denied_without_raising(agent, contract):
    # DATA_ENGINEER can run the pipeline (RUN_PIPELINE) but not publish
    # (PUBLISH_DATA_PRODUCT is REGULATORY_REPORTING/RISK/ADMIN only) — this
    # must be reported, not raised, since it's by design (§2.12), not a bug.
    channel = _channel(count=10, bad_record_rate=0.0, seed=4)
    report = agent.run("alice", RoleName.DATA_ENGINEER, [channel], contract, "2026-06", "dp1")

    assert report.publish_outcome == str(PolicyOutcome.DENY)
    assert "PERMISSION_DENIED" in report.publish_reason
    # The rest of the run still completed fully.
    assert report.governed_count == 10


def test_quarantine_reason_codes_are_reported(agent, contract):
    channel = _channel(count=20, bad_record_rate=0.25, seed=5)
    report = agent.run("bob", RoleName.ADMIN, [channel], contract, "2026-06", "dp1")
    assert set(report.reason_code_counts) <= {
        "NEGATIVE_BALANCE",
        "MISSING_CREDIT_SCORE",
        "INVALID_CREDIT_GRADE",
        "NULL_MANDATORY_FIELD",
    }
    assert sum(report.reason_code_counts.values()) >= report.quarantined_count


def test_misconfigured_role_without_run_pipeline_raises(agent, contract):
    # FINANCE holds neither RUN_PIPELINE nor PUBLISH_DATA_PRODUCT — AG-1
    # should never even be invoked on its behalf; a denial this early in
    # the fixed plan is a caller misconfiguration, not a normal outcome.
    channel = _channel(count=5, bad_record_rate=0.0, seed=7)
    with pytest.raises(ToolCallDeniedError) as exc_info:
        agent.run("erin", RoleName.FINANCE, [channel], contract, "2026-06", "dp1")
    assert exc_info.value.stage == "ingest"


def test_session_is_traceable_end_to_end(agent, contract, connection):
    channel = _channel(count=5, bad_record_rate=0.0, seed=6)
    report = agent.run("bob", RoleName.ADMIN, [channel], contract, "2026-06", "dp1")

    from fry14_engine.agent_trace.logger import AgentTraceLogger

    events = AgentTraceLogger(connection).read_session(report.session_id)
    event_types = [str(e.event_type) for e in events]
    assert event_types[0] == "USER_REQUEST"
    assert "TOOL_CALL" in event_types
    assert "POLICY_DECISION" in event_types
    assert all(e.agent_id == str(AgentId.AG1_PIPELINE_OPERATIONS) for e in events)
