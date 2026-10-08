"""AG-2 Data Quality Triage Agent (C19) integration tests: root-cause
hypothesis -> AgentProposal -> approval -> reprocessing, using a fake
`LlmClient` (no real model call; see agent_runtime/models.py's own scope
note). Covers "no data change without a recorded approval" and
"reprocessed records keep lineage to quarantine IDs"
(03-implementation-plan.md Phase 10 test list).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fry14_engine.agent_runtime.ag1_pipeline_operations import PipelineOperationsAgent
from fry14_engine.agent_runtime.ag2_data_quality_triage import (
    DataQualityTriageAgent,
    NoDataChangeWithoutApprovalError,
    ProposalTypeChoice,
    RemediationAction,
    RootCauseHypothesis,
    RootCauseHypothesisList,
)
from fry14_engine.agent_runtime.models import SessionStatus
from fry14_engine.agent_runtime.runtime import AgentRuntime
from fry14_engine.approval_queue.models import ProposalDraft, ProposalStatus, ProposalType
from fry14_engine.approval_queue.service import ApprovalQueueService
from fry14_engine.common.enums import AgentId, IngestionChannel, Permission, RoleName
from fry14_engine.contracts.registry import ContractRegistry
from fry14_engine.db import bootstrap, get_connection
from fry14_engine.ingestion.adapter import IngestionAdapter, IngestionBatch
from fry14_engine.mcp_server.models import ToolContext
from fry14_engine.mcp_server.server import McpToolServer
from fry14_engine.orchestrator.models import ChannelSource
from fry14_engine.pii.governed_store import GovernedStore
from fry14_engine.pii.hashing_service import PIIHashingService
from fry14_engine.synthetic.generator import (
    generate_loan_records,
    generate_negative_balance_entity_batch,
    generate_schema_change_drops_credit_score_batch,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_HASH_KEY = "ag2-test-key"


class _FakeAdapter(IngestionAdapter):
    channel = IngestionChannel.BATCH
    source_system_of_record = "LEGACY_CORE"

    def __init__(self, records: list[dict]) -> None:
        self._records = records

    def read(self) -> IngestionBatch:
        batch = IngestionBatch()
        for payload in self._records:
            self._normalize_into(payload, batch)
        return batch


class _FakeLlmClient:
    model_id = "fake-triage-model"
    prompt_template_version = "1.0.0"

    def __init__(self, hypotheses: list[RootCauseHypothesis]):
        self._hypotheses = hypotheses

    def complete(self, request, response_schema):
        return RootCauseHypothesisList(hypotheses=self._hypotheses).model_dump(mode="json"), 120, 80


def _remediation_hypothesis() -> RootCauseHypothesis:
    return RootCauseHypothesis(
        reason_code="MISSING_CREDIT_SCORE",
        cluster_key="source_system=LEGACY_CORE",
        root_cause="LEGACY_CORE's schema change dropped credit_score",
        citation=(
            "5/5 (100%) of this cluster's records are null for credit_score, all from LEGACY_CORE"
        ),
        proposal_type=ProposalTypeChoice.REMEDIATION_RULE,
        rationale="Default missing credit_score to 650 pending the upstream fix",
        remediation_field="credit_score",
        remediation_action=RemediationAction.SET_DEFAULT,
        remediation_value=650,
    )


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
def quarantined_run(connection, contract):
    """Ingests a clean batch plus a labeled schema-change batch through
    AG-1 so AG-2 has a real, attributable MISSING_CREDIT_SCORE cluster to
    triage."""
    server = McpToolServer(connection, PIIHashingService(TEST_HASH_KEY))
    runtime = AgentRuntime(connection)
    ag1 = PipelineOperationsAgent(connection, server, runtime)

    good = generate_loan_records(count=10, bad_record_rate=0.0, seed=1)
    bad = generate_schema_change_drops_credit_score_batch(
        count=5, source_system_of_record="LEGACY_CORE", seed=2, start_index=100
    )
    channel = ChannelSource(
        adapter=_FakeAdapter(good + bad),
        source_entity_code="ENTITY_001",
        source_system_of_record="LEGACY_CORE",
    )
    report = ag1.run("alice", RoleName.ADMIN, [channel], contract, "2026-06", "dp1")
    assert report.reason_code_counts.get("MISSING_CREDIT_SCORE") == 5
    return server, runtime


def test_triage_produces_a_proposal_citing_the_real_cluster_stats(connection, quarantined_run):
    server, runtime = quarantined_run
    ag2 = DataQualityTriageAgent(connection, server, runtime)

    proposals = ag2.run(
        "alice", RoleName.DATA_ENGINEER, _FakeLlmClient([_remediation_hypothesis()])
    )

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.status == ProposalStatus.PENDING
    assert proposal.payload["reason_code"] == "MISSING_CREDIT_SCORE"
    assert "LEGACY_CORE" in proposal.evidence[0]


def test_reprocess_without_approval_raises_and_changes_nothing(
    connection, quarantined_run, contract
):
    server, runtime = quarantined_run
    ag2 = DataQualityTriageAgent(connection, server, runtime)
    proposals = ag2.run(
        "alice", RoleName.DATA_ENGINEER, _FakeLlmClient([_remediation_hypothesis()])
    )
    proposal = proposals[0]
    assert proposal.status == ProposalStatus.PENDING

    with pytest.raises(NoDataChangeWithoutApprovalError):
        ag2.reprocess_after_approval(proposal, contract)

    governed_with_lineage = connection.execute(
        "SELECT COUNT(*) FROM governed.loan_record WHERE original_quarantine_id IS NOT NULL"
    ).fetchone()[0]
    assert governed_with_lineage == 0


def test_approved_proposal_reprocesses_with_quarantine_lineage(
    connection, quarantined_run, contract
):
    server, runtime = quarantined_run
    ag2 = DataQualityTriageAgent(connection, server, runtime)
    proposals = ag2.run(
        "alice", RoleName.DATA_ENGINEER, _FakeLlmClient([_remediation_hypothesis()])
    )
    proposal = proposals[0]

    approval_queue = ApprovalQueueService(connection)
    approved = approval_queue.approve(proposal.proposal_id, "dave", RoleName.DATA_ENGINEER)

    reprocessed_count, still_quarantined_count = ag2.reprocess_after_approval(approved, contract)

    assert reprocessed_count == 5
    assert still_quarantined_count == 0

    rows = connection.execute(
        "SELECT loan_id, original_quarantine_id, credit_score FROM governed.loan_record "
        "WHERE original_quarantine_id IS NOT NULL ORDER BY loan_id"
    ).fetchall()
    assert len(rows) == 5
    assert all(credit_score == 650 for _loan_id, _qid, credit_score in rows)
    assert all(quarantine_id for _loan_id, quarantine_id, _credit_score in rows)

    quarantine_status_counts = connection.execute(
        "SELECT remediation_status, COUNT(*) FROM quarantine.quarantine_record "
        "GROUP BY remediation_status"
    ).fetchall()
    assert dict(quarantine_status_counts) == {"RESOLVED": 5}


def test_reprocessed_records_flow_through_risk_calculation(connection, quarantined_run, contract):
    server, runtime = quarantined_run
    ag2 = DataQualityTriageAgent(connection, server, runtime)
    proposals = ag2.run(
        "alice", RoleName.DATA_ENGINEER, _FakeLlmClient([_remediation_hypothesis()])
    )
    approval_queue = ApprovalQueueService(connection)
    approved = approval_queue.approve(proposals[0].proposal_id, "dave", RoleName.DATA_ENGINEER)
    ag2.reprocess_after_approval(approved, contract)

    reprocessed = [
        r
        for r in GovernedStore(connection).read_by_pipeline_run_id(
            connection.execute(
                "SELECT DISTINCT pipeline_run_id FROM governed.loan_record "
                "WHERE original_quarantine_id IS NOT NULL LIMIT 1"
            ).fetchone()[0]
        )
    ]
    assert len(reprocessed) == 5
    assert all(r.original_quarantine_id is not None for r in reprocessed)
    assert all(r.credit_score == 650 for r in reprocessed)


def test_abs_value_remediation_reprocesses_negative_balance_cluster(connection, contract):
    server = McpToolServer(connection, PIIHashingService(TEST_HASH_KEY))
    runtime = AgentRuntime(connection)
    ag1 = PipelineOperationsAgent(connection, server, runtime)

    good = generate_loan_records(count=10, bad_record_rate=0.0, seed=20)
    bad = generate_negative_balance_entity_batch(
        count=4, counterparty_id="CP-99999", seed=21, start_index=200
    )
    channel = ChannelSource(
        adapter=_FakeAdapter(good + bad),
        source_entity_code="ENTITY_001",
        source_system_of_record="LEGACY_CORE",
    )
    report = ag1.run("alice", RoleName.ADMIN, [channel], contract, "2026-06", "dp1")
    assert report.reason_code_counts.get("NEGATIVE_BALANCE") == 4

    hypothesis = RootCauseHypothesis(
        reason_code="NEGATIVE_BALANCE",
        cluster_key="counterparty_id=CP-99999",
        root_cause="CP-99999's feed sends signed-negative balances",
        citation="4/4 (100%) of this cluster share counterparty_id=CP-99999",
        proposal_type=ProposalTypeChoice.REMEDIATION_RULE,
        rationale="Take the absolute value pending the upstream fix",
        remediation_field="outstanding_balance",
        remediation_action=RemediationAction.ABS_VALUE,
    )
    ag2 = DataQualityTriageAgent(connection, server, runtime)
    proposals = ag2.run("alice", RoleName.DATA_ENGINEER, _FakeLlmClient([hypothesis]))
    approved = ApprovalQueueService(connection).approve(
        proposals[0].proposal_id, "dave", RoleName.DATA_ENGINEER
    )

    reprocessed_count, still_quarantined_count = ag2.reprocess_after_approval(approved, contract)
    assert reprocessed_count == 4
    assert still_quarantined_count == 0


def test_remediation_that_still_fails_validation_stays_quarantined(
    connection, quarantined_run, contract
):
    server, runtime = quarantined_run
    ag2 = DataQualityTriageAgent(connection, server, runtime)
    # Sets credit_score to None again (a no-op "fix") so the record is
    # still MISSING_CREDIT_SCORE after "remediation" — reprocessing must
    # not fabricate a pass.
    hypothesis = _remediation_hypothesis().model_copy(update={"remediation_value": None})
    proposals = ag2.run("alice", RoleName.DATA_ENGINEER, _FakeLlmClient([hypothesis]))
    approved = ApprovalQueueService(connection).approve(
        proposals[0].proposal_id, "dave", RoleName.DATA_ENGINEER
    )

    reprocessed_count, still_quarantined_count = ag2.reprocess_after_approval(approved, contract)
    assert reprocessed_count == 0
    assert still_quarantined_count == 5


def test_contract_amendment_hypothesis_uses_propose_contract_change(connection, quarantined_run):
    server, runtime = quarantined_run
    ag2 = DataQualityTriageAgent(connection, server, runtime)
    hypothesis = RootCauseHypothesis(
        reason_code="MISSING_CREDIT_SCORE",
        cluster_key="source_system=LEGACY_CORE",
        root_cause="credit_score should be nullable for this source while it backfills",
        citation="5/5 (100%) of this cluster are null for credit_score",
        proposal_type=ProposalTypeChoice.CONTRACT_AMENDMENT,
        rationale="Relax the null constraint temporarily",
        remediation_field="credit_score",
    )

    proposals = ag2.run("alice", RoleName.DATA_ENGINEER, _FakeLlmClient([hypothesis]))

    assert len(proposals) == 1
    assert proposals[0].proposal_type == ProposalType.CONTRACT_AMENDMENT


def test_source_ticket_hypothesis_creates_a_proposal(connection, quarantined_run):
    server, runtime = quarantined_run
    ag2 = DataQualityTriageAgent(connection, server, runtime)
    hypothesis = RootCauseHypothesis(
        reason_code="MISSING_CREDIT_SCORE",
        cluster_key="source_system=LEGACY_CORE",
        root_cause="Upstream schema change dropped credit_score entirely",
        citation="5/5 (100%) of this cluster are null for credit_score",
        proposal_type=ProposalTypeChoice.SOURCE_TICKET,
        rationale="File a ticket with the LEGACY_CORE team to restore the field",
    )

    proposals = ag2.run("alice", RoleName.DATA_ENGINEER, _FakeLlmClient([hypothesis]))

    assert len(proposals) == 1
    assert proposals[0].proposal_type == ProposalType.SOURCE_TICKET


def test_run_denied_quarantine_summary_access_returns_no_proposals(connection, quarantined_run):
    server, runtime = quarantined_run
    ag2 = DataQualityTriageAgent(connection, server, runtime)

    # FINANCE lacks REMEDIATE_QUARANTINE: get_quarantine_summary is denied
    # before the LLM is ever called.
    proposals = ag2.run("erin", RoleName.FINANCE, _FakeLlmClient([_remediation_hypothesis()]))

    assert proposals == []


def test_get_quarantine_summary_tool_is_policy_gated(connection, quarantined_run):
    server, _runtime = quarantined_run
    ctx = ToolContext(AgentId.AG2_DATA_QUALITY_TRIAGE, RoleName.FINANCE, "sess-x", "erin")
    result = server.get_quarantine_summary(ctx)
    assert result.result is None


def test_propose_contract_change_tool_creates_a_pending_proposal(connection):
    server = McpToolServer(connection, PIIHashingService(TEST_HASH_KEY))
    ctx = ToolContext(AgentId.AG2_DATA_QUALITY_TRIAGE, RoleName.DATA_ENGINEER, "sess-y", "alice")
    draft = ProposalDraft(
        proposal_type=ProposalType.CONTRACT_AMENDMENT,
        payload={"field": "credit_score"},
        rationale="test",
        required_permission=Permission.APPROVE_CONTRACT_CHANGE,
    )

    result = server.propose_contract_change(ctx, draft)

    assert result.decision.proposal_id is not None
    proposal = ApprovalQueueService(connection).read(result.decision.proposal_id)
    assert proposal.status == ProposalStatus.PENDING


def test_denied_summary_ends_session_in_error_status(connection, quarantined_run):
    server, runtime = quarantined_run
    ag2 = DataQualityTriageAgent(connection, server, runtime)
    ag2.run("erin", RoleName.FINANCE, _FakeLlmClient([_remediation_hypothesis()]))

    sessions = connection.execute(
        "SELECT session_id, status FROM agent_governance.agent_session "
        "WHERE agent_id = ? ORDER BY created_at DESC LIMIT 1",
        [str(AgentId.AG2_DATA_QUALITY_TRIAGE)],
    ).fetchone()
    assert sessions[1] == str(SessionStatus.ERROR)
