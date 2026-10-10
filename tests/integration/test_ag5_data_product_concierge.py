"""AG-5 Data Product Concierge Agent (C22) integration tests: Flow C from
02-design-document.md §4.1. The concierge's structural refusal (no SQL
surface at all — see the agent module's own scope note) and
"concierge results equal direct sandbox queries" (requirements.md's own
Phase 11 test list).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fry14_engine.agent_runtime.ag1_pipeline_operations import PipelineOperationsAgent
from fry14_engine.agent_runtime.ag5_data_product_concierge import (
    ConciergeQueryRequest,
    DataProductConciergeAgent,
)
from fry14_engine.agent_runtime.runtime import AgentRuntime
from fry14_engine.catalog.query_sandbox import QuerySandboxService
from fry14_engine.common.enums import IngestionChannel, RoleName
from fry14_engine.contracts.registry import ContractRegistry
from fry14_engine.db import bootstrap, get_connection
from fry14_engine.ingestion.adapter import IngestionAdapter, IngestionBatch
from fry14_engine.mcp_server.server import McpToolServer
from fry14_engine.orchestrator.models import ChannelSource
from fry14_engine.pii.hashing_service import PIIHashingService
from fry14_engine.synthetic.generator import generate_loan_records

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_HASH_KEY = "ag5-test-key"


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


class _FakeLlmClient:
    model_id = "fake-ag5-model"
    prompt_template_version = "1.0.0"

    def __init__(self, response: ConciergeQueryRequest):
        self._response = response

    def complete(self, request, response_schema):
        return self._response.model_dump(mode="json"), 20, 15


@pytest.fixture
def connection(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    yield con
    con.close()


@pytest.fixture
def contract():
    return ContractRegistry(REPO_ROOT / "config" / "contracts").get_active("commercial_loan")


@pytest.fixture
def published_run(connection, contract):
    server = McpToolServer(connection, PIIHashingService(TEST_HASH_KEY))
    runtime = AgentRuntime(connection)
    ag1 = PipelineOperationsAgent(connection, server, runtime)
    records = generate_loan_records(count=15, bad_record_rate=0.0, seed=2)
    channel = ChannelSource(
        adapter=_FakeAdapter(records),
        source_entity_code="ENTITY_001",
        source_system_of_record="CORE",
    )
    report = ag1.run("bob", RoleName.ADMIN, [channel], contract, "2026-06", "dp1")
    return server, runtime, report


def test_answer_matches_direct_sandbox_query(connection, published_run):
    server, runtime, _report = published_run
    agent = DataProductConciergeAgent(connection, server, runtime)
    response = ConciergeQueryRequest(reporting_period="2026-06", schema_version="1.0.0")

    answer = agent.answer(
        "erin", RoleName.FINANCE, _FakeLlmClient(response), "Total RWA last quarter?"
    )

    direct_rows = QuerySandboxService(connection).query_schedule(
        RoleName.FINANCE, "2026-06", "1.0.0"
    )
    assert not answer.refused
    assert answer.rows == direct_rows
    assert "query_schedule" in answer.generated_query


def test_llm_initiated_refusal_for_pii_request(connection, published_run):
    server, runtime, _report = published_run
    agent = DataProductConciergeAgent(connection, server, runtime)
    response = ConciergeQueryRequest(
        refused=True, refusal_reason="Cannot provide raw borrower PII."
    )

    answer = agent.answer(
        "erin", RoleName.FINANCE, _FakeLlmClient(response), "Show me John Doe's SSN"
    )

    assert answer.refused
    assert "PII" in answer.message
    assert answer.rows == []


def test_missing_parameters_is_refused_not_guessed(connection, published_run):
    server, runtime, _report = published_run
    agent = DataProductConciergeAgent(connection, server, runtime)
    response = ConciergeQueryRequest(reporting_period=None, schema_version=None)

    answer = agent.answer(
        "erin", RoleName.FINANCE, _FakeLlmClient(response), "What about last quarter?"
    )

    assert answer.refused
    assert answer.rows == []


def test_role_without_query_permission_is_refused_and_logged(connection, published_run):
    server, runtime, _report = published_run
    agent = DataProductConciergeAgent(connection, server, runtime)
    response = ConciergeQueryRequest(reporting_period="2026-06", schema_version="1.0.0")

    answer = agent.answer(
        "alice", RoleName.DATA_ENGINEER, _FakeLlmClient(response), "Total RWA last quarter?"
    )

    assert answer.refused
    assert "PERMISSION_DENIED" in answer.message

    from fry14_engine.agent_trace.logger import AgentTraceLogger

    sessions = connection.execute(
        "SELECT session_id FROM agent_governance.agent_session "
        "WHERE on_behalf_of = 'alice' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    events = AgentTraceLogger(connection).read_session(sessions[0])
    assert any(str(e.event_type) == "POLICY_DECISION" for e in events)
