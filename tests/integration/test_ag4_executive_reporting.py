"""AG-4 Executive Reporting Agent (C21) integration tests: grounded
narrative drafting over a real `RunReport` and `ScenarioRunResult`, the
Numeric Grounding Checker blocking an injected free number, and
release-via-Approval-Queue. See 02-design-document.md §3.19 and
requirements.md §3.2 (AG-4).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fry14_engine.agent_runtime.ag1_pipeline_operations import PipelineOperationsAgent
from fry14_engine.agent_runtime.ag3_stress_scenario import DraftScenarioRequest, StressScenarioAgent
from fry14_engine.agent_runtime.ag4_executive_reporting import (
    ExecutiveReportingAgent,
    NarrativeDraft,
)
from fry14_engine.agent_runtime.runtime import AgentRuntime
from fry14_engine.approval_queue.service import ApprovalQueueService
from fry14_engine.common.enums import IngestionChannel, RoleName
from fry14_engine.contracts.registry import ContractRegistry
from fry14_engine.db import bootstrap, get_connection
from fry14_engine.grounding.models import GroundingStatus, NarrativeApprovalStatus
from fry14_engine.ingestion.adapter import IngestionAdapter, IngestionBatch
from fry14_engine.mcp_server.server import McpToolServer
from fry14_engine.orchestrator.models import ChannelSource
from fry14_engine.pii.hashing_service import PIIHashingService
from fry14_engine.rbac.service import PermissionDeniedError
from fry14_engine.scenario.models import ScenarioName
from fry14_engine.synthetic.generator import generate_loan_records

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_HASH_KEY = "ag4-test-key"


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
    model_id = "fake-ag4-model"
    prompt_template_version = "1.0.0"

    def __init__(self, template_text: str):
        self._template_text = template_text

    def complete(self, request, response_schema):
        return NarrativeDraft(template_text=self._template_text).model_dump(mode="json"), 60, 40


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
def run_report(connection, contract):
    server = McpToolServer(connection, PIIHashingService(TEST_HASH_KEY))
    runtime = AgentRuntime(connection)
    ag1 = PipelineOperationsAgent(connection, server, runtime)
    records = generate_loan_records(count=10, bad_record_rate=0.0, seed=1)
    channel = ChannelSource(
        adapter=_FakeAdapter(records),
        source_entity_code="ENTITY_001",
        source_system_of_record="CORE",
    )
    return ag1.run("bob", RoleName.ADMIN, [channel], contract, "2026-06", "dp1"), server, runtime


def test_fully_bound_run_narrative_passes_and_creates_a_proposal(connection, run_report):
    report, _server, runtime = run_report
    agent = ExecutiveReportingAgent(connection, runtime)
    template = (
        f"We processed {{{{run:{report.pipeline_run_id}.governed_count}}}} loans "
        f"with a DQ pass rate of {{{{run:{report.pipeline_run_id}.dq_pass_percentage}}}}%."
    )

    narrative, proposal_id = agent.draft_run_narrative(
        "carol", RoleName.REGULATORY_REPORTING, _FakeLlmClient(template), report
    )

    assert narrative.grounding_status == GroundingStatus.PASSED
    assert str(report.governed_count) in narrative.rendered_text
    assert proposal_id is not None


def test_narrative_with_injected_free_number_is_blocked(connection, run_report):
    report, _server, runtime = run_report
    agent = ExecutiveReportingAgent(connection, runtime)
    # A free number (10) instead of a binding — must be caught, not released.
    template = "We processed 10 loans this period."

    narrative, proposal_id = agent.draft_run_narrative(
        "carol", RoleName.REGULATORY_REPORTING, _FakeLlmClient(template), report
    )

    assert narrative.grounding_status == GroundingStatus.FAILED
    assert proposal_id is None
    assert len(ApprovalQueueService(connection).read_pending()) == 0


def test_narrative_citing_the_wrong_run_id_is_unresolved(connection, run_report):
    report, _server, runtime = run_report
    agent = ExecutiveReportingAgent(connection, runtime)
    template = "We processed {{run:some-other-run-id.governed_count}} loans."

    narrative, proposal_id = agent.draft_run_narrative(
        "carol", RoleName.REGULATORY_REPORTING, _FakeLlmClient(template), report
    )

    assert narrative.grounding_status == GroundingStatus.FAILED
    assert proposal_id is None


def test_release_requires_the_approve_narrative_permission(connection, run_report):
    report, _server, runtime = run_report
    agent = ExecutiveReportingAgent(connection, runtime)
    template = f"Governed count: {{{{run:{report.pipeline_run_id}.governed_count}}}}."
    _narrative, proposal_id = agent.draft_run_narrative(
        "carol", RoleName.REGULATORY_REPORTING, _FakeLlmClient(template), report
    )

    with pytest.raises(PermissionDeniedError):
        agent.release(proposal_id, "erin", RoleName.DATA_ENGINEER)


def test_release_marks_narrative_approved(connection, run_report):
    report, _server, runtime = run_report
    agent = ExecutiveReportingAgent(connection, runtime)
    template = f"Governed count: {{{{run:{report.pipeline_run_id}.governed_count}}}}."
    narrative, proposal_id = agent.draft_run_narrative(
        "carol", RoleName.REGULATORY_REPORTING, _FakeLlmClient(template), report
    )

    released = agent.release(proposal_id, "erin", RoleName.RISK)

    assert released.narrative_id == narrative.narrative_id
    assert released.approval_status == NarrativeApprovalStatus.APPROVED
    assert released.released_by == "erin"


def test_run_narrative_can_bind_a_string_field(connection, run_report):
    report, _server, runtime = run_report
    agent = ExecutiveReportingAgent(connection, runtime)
    template = f"Publish outcome was {{{{run:{report.pipeline_run_id}.publish_outcome}}}}."

    narrative, proposal_id = agent.draft_run_narrative(
        "carol", RoleName.REGULATORY_REPORTING, _FakeLlmClient(template), report
    )

    assert narrative.grounding_status == GroundingStatus.PASSED
    assert report.publish_outcome in narrative.rendered_text
    assert proposal_id is not None


def test_scenario_narrative_binds_per_segment_deltas(connection, run_report):
    report, server, runtime = run_report
    ag3 = StressScenarioAgent(connection, server, runtime)
    draft = DraftScenarioRequest(
        reporting_period="2026-06",
        base_scenario=ScenarioName.SEVERELY_ADVERSE,
        supervisory_scenario_version="FED-2026",
    )

    class _Ag3Llm:
        model_id = "m"
        prompt_template_version = "1"

        def complete(self, request, response_schema):
            return draft.model_dump(mode="json"), 10, 10

    drafted = ag3.draft("dave", RoleName.FINANCE, _Ag3Llm(), "Run severely adverse")
    scenario_result = ag3.confirm_and_run(
        drafted.session_id, "dave", RoleName.FINANCE, drafted.spec, report.pipeline_run_id
    )
    segment = scenario_result.comparison_rows[0].portfolio_segment

    ag4 = ExecutiveReportingAgent(connection, runtime)
    template = (
        f"Under the scenario, {segment} EL moved by "
        f"{{{{scenario:{scenario_result.scenario_run_id}.segment.{segment}.delta_el}}}}."
    )
    narrative, proposal_id = ag4.draft_scenario_narrative(
        "dave", RoleName.RISK, _FakeLlmClient(template), scenario_result
    )

    assert narrative.grounding_status == GroundingStatus.PASSED
    assert proposal_id is not None

    # Wrong scenario_run_id -> unresolved, not a false positive from some
    # other stored run's data.
    wrong_id_template = f"EL moved by {{{{scenario:not-the-real-id.segment.{segment}.delta_el}}}}."
    bad_narrative, bad_proposal_id = ag4.draft_scenario_narrative(
        "dave", RoleName.RISK, _FakeLlmClient(wrong_id_template), scenario_result
    )
    assert bad_narrative.grounding_status == GroundingStatus.FAILED
    assert bad_proposal_id is None

    # An attribute path that doesn't exist on ScenarioRunResult at all.
    unknown_field_template = (
        f"Value: {{{{scenario:{scenario_result.scenario_run_id}.not_a_real_field}}}}."
    )
    unknown_narrative, unknown_proposal_id = ag4.draft_scenario_narrative(
        "dave", RoleName.RISK, _FakeLlmClient(unknown_field_template), scenario_result
    )
    assert unknown_narrative.grounding_status == GroundingStatus.FAILED
    assert unknown_proposal_id is None
