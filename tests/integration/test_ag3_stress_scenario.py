"""AG-3 Stress Scenario Agent (C20) integration tests: Flow B from
02-design-document.md §4.1 end-to-end, using a fake `LlmClient` (no real
model call — see agent_runtime/models.py's own scope note).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fry14_engine.agent_runtime.ag1_pipeline_operations import PipelineOperationsAgent
from fry14_engine.agent_runtime.ag3_stress_scenario import (
    AG3Status,
    DraftScenarioRequest,
    RunNotConfirmedError,
    StressScenarioAgent,
)
from fry14_engine.agent_runtime.runtime import AgentRuntime
from fry14_engine.common.enums import IngestionChannel, RoleName
from fry14_engine.contracts.registry import ContractRegistry
from fry14_engine.db import bootstrap, get_connection
from fry14_engine.ingestion.adapter import IngestionAdapter, IngestionBatch
from fry14_engine.mcp_server.server import McpToolServer
from fry14_engine.orchestrator.models import ChannelSource
from fry14_engine.pii.hashing_service import PIIHashingService
from fry14_engine.scenario.models import ScenarioName
from fry14_engine.scenario.spec_models import AdhocShock, AdhocShockType
from fry14_engine.synthetic.generator import generate_loan_records

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_HASH_KEY = "ag3-test-key"


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
    model_id = "fake-ag3-model"
    prompt_template_version = "1.0.0"

    def __init__(self, draft: DraftScenarioRequest):
        self._draft = draft

    def complete(self, request, response_schema):
        return self._draft.model_dump(mode="json"), 50, 30


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
def base_run(connection, contract):
    server = McpToolServer(connection, PIIHashingService(TEST_HASH_KEY))
    runtime = AgentRuntime(connection)
    ag1 = PipelineOperationsAgent(connection, server, runtime)
    records = generate_loan_records(count=15, bad_record_rate=0.0, seed=1)
    channel = ChannelSource(
        adapter=_FakeAdapter(records),
        source_entity_code="ENTITY_001",
        source_system_of_record="CORE",
    )
    report = ag1.run("bob", RoleName.ADMIN, [channel], contract, "2026-06", "dp1")
    return server, runtime, report


def test_supervisory_request_reaches_ready_to_confirm(connection, base_run):
    server, runtime, _report = base_run
    agent = StressScenarioAgent(connection, server, runtime)
    draft = DraftScenarioRequest(
        reporting_period="2026-06",
        base_scenario=ScenarioName.SEVERELY_ADVERSE,
        supervisory_scenario_version="FED-2026",
    )

    result = agent.draft("dave", RoleName.FINANCE, _FakeLlmClient(draft), "Run severely adverse")

    assert result.status == AG3Status.READY_TO_CONFIRM
    assert result.spec is not None
    assert result.spec.classification == "SUPERVISORY"
    assert "Confirm to proceed" in result.plain_language_summary


def test_adhoc_shock_request_is_classified_exploratory(connection, base_run):
    server, runtime, _report = base_run
    agent = StressScenarioAgent(connection, server, runtime)
    draft = DraftScenarioRequest(
        reporting_period="2026-06",
        adhoc_shocks=[
            AdhocShock(
                variable="TREASURY_10Y",
                shock_type=AdhocShockType.ADD_BPS,
                magnitude=200,
                quarters=[1, 2, 3],
            )
        ],
    )

    result = agent.draft("dave", RoleName.FINANCE, _FakeLlmClient(draft), "Add 200bps to the 10yr")

    assert result.status == AG3Status.READY_TO_CONFIRM
    assert result.spec.classification == "EXPLORATORY"
    assert "Exploratory" in result.plain_language_summary


def test_ambiguous_request_asks_a_clarifying_question(connection, base_run):
    server, runtime, _report = base_run
    agent = StressScenarioAgent(connection, server, runtime)
    draft = DraftScenarioRequest(
        needs_clarification=True,
        clarifying_question="Apply the +200bps to the 10-year Treasury, the BBB yield, or both?",
    )

    result = agent.draft("dave", RoleName.FINANCE, _FakeLlmClient(draft), "Add a 200bps rate shock")

    assert result.status == AG3Status.NEEDS_CLARIFICATION
    assert "10-year Treasury" in result.clarifying_question
    assert result.spec is None


def test_clarification_answer_is_threaded_into_the_second_draft(connection, base_run):
    server, runtime, _report = base_run
    agent = StressScenarioAgent(connection, server, runtime)
    first_draft = DraftScenarioRequest(
        needs_clarification=True, clarifying_question="Which variable?"
    )
    first = agent.draft("dave", RoleName.FINANCE, _FakeLlmClient(first_draft), "Add a rate shock")
    assert first.status == AG3Status.NEEDS_CLARIFICATION

    second_draft = DraftScenarioRequest(
        reporting_period="2026-06",
        adhoc_shocks=[
            AdhocShock(
                variable="TREASURY_10Y",
                shock_type=AdhocShockType.ADD_BPS,
                magnitude=200,
                quarters=[1],
            )
        ],
    )
    second = agent.draft(
        "dave",
        RoleName.FINANCE,
        _FakeLlmClient(second_draft),
        "Add a rate shock",
        clarification_answer="The 10-year Treasury",
    )
    assert second.status == AG3Status.READY_TO_CONFIRM


def test_invalid_draft_is_rejected_not_raised(connection, base_run):
    # base_scenario set without supervisory_scenario_version is a real
    # ScenarioSpecValidationError build_scenario_spec raises — AG-3 must
    # catch it and report REJECTED, not let it propagate as a crash.
    server, runtime, _report = base_run
    agent = StressScenarioAgent(connection, server, runtime)
    draft = DraftScenarioRequest(
        reporting_period="2026-06", base_scenario=ScenarioName.SEVERELY_ADVERSE
    )

    result = agent.draft("dave", RoleName.FINANCE, _FakeLlmClient(draft), "Run a baseline check")

    assert result.status == AG3Status.REJECTED
    assert result.rejection_reason is not None
    assert result.spec is None


def test_build_scenario_spec_denied_for_role_without_permission(connection, base_run):
    server, runtime, _report = base_run
    agent = StressScenarioAgent(connection, server, runtime)
    draft = DraftScenarioRequest(
        reporting_period="2026-06",
        base_scenario=ScenarioName.SEVERELY_ADVERSE,
        supervisory_scenario_version="FED-2026",
    )

    result = agent.draft(
        "alice", RoleName.DATA_ENGINEER, _FakeLlmClient(draft), "Run severely adverse"
    )

    assert result.status == AG3Status.REJECTED
    assert "PERMISSION_DENIED" in result.rejection_reason


def test_plain_language_summary_mentions_restricted_portfolio_scope(connection, base_run):
    server, runtime, _report = base_run
    agent = StressScenarioAgent(connection, server, runtime)
    draft = DraftScenarioRequest(
        reporting_period="2026-06",
        base_scenario=ScenarioName.SEVERELY_ADVERSE,
        supervisory_scenario_version="FED-2026",
        portfolio_segments=["LARGE_CORPORATE"],
    )

    result = agent.draft("dave", RoleName.FINANCE, _FakeLlmClient(draft), "Run on large corporate")

    assert result.status == AG3Status.READY_TO_CONFIRM
    assert "segments LARGE_CORPORATE" in result.plain_language_summary
    assert "restricted to" in result.plain_language_summary


def test_confirm_and_run_produces_a_real_scenario_run_result(connection, base_run):
    server, runtime, report = base_run
    agent = StressScenarioAgent(connection, server, runtime)
    draft = DraftScenarioRequest(
        reporting_period="2026-06",
        base_scenario=ScenarioName.SEVERELY_ADVERSE,
        supervisory_scenario_version="FED-2026",
    )
    drafted = agent.draft("dave", RoleName.FINANCE, _FakeLlmClient(draft), "Run severely adverse")

    run_result = agent.confirm_and_run(
        drafted.session_id, "dave", RoleName.FINANCE, drafted.spec, report.pipeline_run_id
    )

    assert run_result.stressed_loan_metrics
    assert run_result.input_hash

    interpretation = StressScenarioAgent.interpret(run_result)
    assert "RWA moved through" in interpretation
    assert run_result.classification in interpretation


def test_confirm_and_run_denied_for_role_without_run_stress_scenario(connection, base_run):
    server, runtime, report = base_run
    agent = StressScenarioAgent(connection, server, runtime)
    draft = DraftScenarioRequest(
        reporting_period="2026-06",
        base_scenario=ScenarioName.SEVERELY_ADVERSE,
        supervisory_scenario_version="FED-2026",
    )
    drafted = agent.draft("dave", RoleName.FINANCE, _FakeLlmClient(draft), "Run severely adverse")

    with pytest.raises(RunNotConfirmedError):
        agent.confirm_and_run(
            drafted.session_id,
            "erin",
            RoleName.DATA_ENGINEER,
            drafted.spec,
            report.pipeline_run_id,
        )


def test_empty_scenario_run_interpretation_handles_no_loans_in_scope(connection, base_run):
    server, runtime, report = base_run
    agent = StressScenarioAgent(connection, server, runtime)
    draft = DraftScenarioRequest(
        reporting_period="2026-06",
        base_scenario=ScenarioName.SEVERELY_ADVERSE,
        supervisory_scenario_version="FED-2026",
        asset_classes=["NONEXISTENT_CLASS"],
    )
    drafted = agent.draft("dave", RoleName.FINANCE, _FakeLlmClient(draft), "Run on a weird scope")
    run_result = agent.confirm_and_run(
        drafted.session_id, "dave", RoleName.FINANCE, drafted.spec, report.pipeline_run_id
    )

    assert run_result.stressed_loan_metrics == []
    assert "nothing to report" in StressScenarioAgent.interpret(run_result)
