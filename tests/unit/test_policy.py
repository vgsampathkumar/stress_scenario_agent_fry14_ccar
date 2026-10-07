"""Policy Enforcement Point (C24) tests against the real, seeded tool
catalog (schemas/013_agent_governance.sql) — every tool x role x autonomy
combination the plan calls for, plus session limits and the structural
guarantee that no agent ever gets an APPROVE_* permission. See
02-design-document.md §3.14 and requirements.md §3.3-3.4.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fry14_engine.agent_trace.logger import AgentTraceLogger
from fry14_engine.agent_trace.models import AgentTraceEventType
from fry14_engine.approval_queue.models import ProposalDraft, ProposalType
from fry14_engine.approval_queue.service import ApprovalQueueService
from fry14_engine.common.enums import AgentId, Permission, RoleName
from fry14_engine.db import bootstrap, get_connection
from fry14_engine.policy.models import PolicyOutcome
from fry14_engine.policy.pep import PolicyEnforcementPoint, ProposalDraftRequiredError
from fry14_engine.policy.store import PolicyStore, ToolPolicyNotFoundError


@pytest.fixture
def connection(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    yield con
    con.close()


@pytest.fixture
def pep(connection) -> PolicyEnforcementPoint:
    trace_logger = AgentTraceLogger(connection)
    approval_queue_service = ApprovalQueueService(connection)
    return PolicyEnforcementPoint(PolicyStore(connection), approval_queue_service, trace_logger)


def test_autonomous_tool_allowed_for_correct_agent_and_role(pep: PolicyEnforcementPoint):
    decision = pep.decide(
        "ingest_batch", AgentId.AG1_PIPELINE_OPERATIONS, RoleName.DATA_ENGINEER, "sess-1", "alice"
    )
    assert decision.outcome == PolicyOutcome.ALLOW


def test_autonomous_tool_denied_for_wrong_agent(pep: PolicyEnforcementPoint):
    decision = pep.decide(
        "ingest_batch", AgentId.AG3_STRESS_SCENARIO, RoleName.DATA_ENGINEER, "sess-1", "alice"
    )
    assert decision.outcome == PolicyOutcome.DENY
    assert "AGENT_NOT_ALLOWED" in decision.reason


def test_autonomous_tool_denied_for_role_without_permission(pep: PolicyEnforcementPoint):
    decision = pep.decide(
        "ingest_batch", AgentId.AG1_PIPELINE_OPERATIONS, RoleName.FINANCE, "sess-1", "alice"
    )
    assert decision.outcome == PolicyOutcome.DENY
    assert "PERMISSION_DENIED" in decision.reason


def test_human_only_tool_always_denied_even_with_permission(pep: PolicyEnforcementPoint):
    # apply_remediation is HUMAN_ONLY with an empty allowed_agents list —
    # denied at the agent-allowlist check, before autonomy is even reached.
    decision = pep.decide(
        "apply_remediation",
        AgentId.AG2_DATA_QUALITY_TRIAGE,
        RoleName.DATA_ENGINEER,
        "sess-1",
        "alice",
    )
    assert decision.outcome == PolicyOutcome.DENY
    assert "AGENT_NOT_ALLOWED" in decision.reason


def test_confirm_tool_requires_confirmation_first(pep: PolicyEnforcementPoint):
    decision = pep.decide(
        "run_stress_scenario", AgentId.AG3_STRESS_SCENARIO, RoleName.FINANCE, "sess-1", "dave"
    )
    assert decision.outcome == PolicyOutcome.CONFIRM_REQUIRED


def test_confirm_tool_allowed_once_confirmed(pep: PolicyEnforcementPoint):
    decision = pep.decide(
        "run_stress_scenario",
        AgentId.AG3_STRESS_SCENARIO,
        RoleName.FINANCE,
        "sess-1",
        "dave",
        already_confirmed=True,
    )
    assert decision.outcome == PolicyOutcome.ALLOW


def test_propose_tool_without_condition_breach_is_allowed(pep: PolicyEnforcementPoint):
    decision = pep.decide(
        "publish_data_product",
        AgentId.AG1_PIPELINE_OPERATIONS,
        RoleName.REGULATORY_REPORTING,
        "sess-1",
        "carol",
        conditions_context={"dq_pass_rate_below_threshold": False},
    )
    assert decision.outcome == PolicyOutcome.ALLOW


def test_propose_tool_escalates_on_condition_breach_and_creates_proposal(
    pep: PolicyEnforcementPoint, connection
):
    draft = ProposalDraft(
        proposal_type=ProposalType.PUBLISH_OVERRIDE,
        payload={"data_product_id": "dp1"},
        rationale="DQ below threshold",
        required_permission=Permission.PUBLISH_DATA_PRODUCT,
    )
    decision = pep.decide(
        "publish_data_product",
        AgentId.AG1_PIPELINE_OPERATIONS,
        RoleName.REGULATORY_REPORTING,
        "sess-1",
        "carol",
        conditions_context={"dq_pass_rate_below_threshold": True},
        proposal_draft=draft,
    )
    assert decision.outcome == PolicyOutcome.PROPOSE
    assert decision.proposal_id

    proposal = ApprovalQueueService(connection).read_pending()[0]
    assert proposal.proposal_id == decision.proposal_id
    assert proposal.requested_by == "carol"
    assert proposal.proposing_agent == str(AgentId.AG1_PIPELINE_OPERATIONS)


def test_propose_without_draft_raises(pep: PolicyEnforcementPoint):
    with pytest.raises(ProposalDraftRequiredError):
        pep.decide(
            "publish_data_product",
            AgentId.AG1_PIPELINE_OPERATIONS,
            RoleName.REGULATORY_REPORTING,
            "sess-1",
            "carol",
            conditions_context={"dq_pass_rate_below_threshold": True},
        )


def test_propose_base_autonomy_tool_without_permission_is_denied_before_proposing(
    pep: PolicyEnforcementPoint,
):
    decision = pep.decide(
        "propose_contract_change",
        AgentId.AG2_DATA_QUALITY_TRIAGE,
        RoleName.FINANCE,
        "sess-1",
        "alice",
    )
    assert decision.outcome == PolicyOutcome.DENY
    assert "PERMISSION_DENIED" in decision.reason


def test_propose_contract_change_escalates_for_authorized_role(pep: PolicyEnforcementPoint):
    draft = ProposalDraft(
        proposal_type=ProposalType.CONTRACT_AMENDMENT,
        payload={"field": "credit_score", "change": "widen allowed_range"},
        rationale="repeated range violations",
        required_permission=Permission.APPROVE_CONTRACT_CHANGE,
    )
    decision = pep.decide(
        "propose_contract_change",
        AgentId.AG2_DATA_QUALITY_TRIAGE,
        RoleName.DATA_ENGINEER,
        "sess-1",
        "alice",
        proposal_draft=draft,
    )
    assert decision.outcome == PolicyOutcome.PROPOSE


def test_session_call_limit_denies_once_exceeded(pep: PolicyEnforcementPoint, connection):
    # A test-local policy row with a deliberately small limit, rather than
    # looping real calls against a seeded limit of 10+.
    connection.execute(
        "INSERT INTO agent_governance.tool_policy "
        "(tool_name, required_permission, autonomy, allowed_agents, max_calls_per_session) "
        "VALUES ('test_tool', 'RUN_PIPELINE', 'AUTONOMOUS', ['AG-1'], 2)"
    )
    trace_logger = AgentTraceLogger(connection)
    for _ in range(2):
        trace_logger.log(
            AgentTraceEventType.TOOL_CALL,
            session_id="sess-1",
            agent_id=str(AgentId.AG1_PIPELINE_OPERATIONS),
            on_behalf_of="alice",
            tool_name="test_tool",
        )

    decision = pep.decide(
        "test_tool", AgentId.AG1_PIPELINE_OPERATIONS, RoleName.DATA_ENGINEER, "sess-1", "alice"
    )
    assert decision.outcome == PolicyOutcome.DENY
    assert "SESSION_LIMIT_EXCEEDED" in decision.reason


def test_session_call_limit_is_scoped_per_session(pep: PolicyEnforcementPoint, connection):
    connection.execute(
        "INSERT INTO agent_governance.tool_policy "
        "(tool_name, required_permission, autonomy, allowed_agents, max_calls_per_session) "
        "VALUES ('test_tool', 'RUN_PIPELINE', 'AUTONOMOUS', ['AG-1'], 1)"
    )
    trace_logger = AgentTraceLogger(connection)
    trace_logger.log(
        AgentTraceEventType.TOOL_CALL,
        session_id="sess-other",
        agent_id=str(AgentId.AG1_PIPELINE_OPERATIONS),
        on_behalf_of="alice",
        tool_name="test_tool",
    )

    decision = pep.decide(
        "test_tool", AgentId.AG1_PIPELINE_OPERATIONS, RoleName.DATA_ENGINEER, "sess-1", "alice"
    )
    assert decision.outcome == PolicyOutcome.ALLOW


def test_every_decision_writes_a_policy_decision_trace_event(
    pep: PolicyEnforcementPoint, connection
):
    pep.decide(
        "ingest_batch", AgentId.AG1_PIPELINE_OPERATIONS, RoleName.DATA_ENGINEER, "sess-1", "alice"
    )
    events = AgentTraceLogger(connection).read_session("sess-1")
    assert len(events) == 1
    assert events[0].event_type == AgentTraceEventType.POLICY_DECISION
    assert events[0].tool_name == "ingest_batch"


def test_no_seeded_tool_requires_an_approve_permission(connection):
    """Structural guarantee from design doc §2.12: agents never hold any
    APPROVE_* permission. No MCP tool in the catalog should even be gated
    behind one — approvals happen exclusively through the Approval Queue
    Service, never as a directly callable tool."""
    rows = connection.execute(
        "SELECT tool_name, required_permission FROM agent_governance.tool_policy"
    ).fetchall()
    assert rows  # sanity: the catalog is actually seeded
    for tool_name, required_permission in rows:
        assert not required_permission.startswith(
            "APPROVE_"
        ), f"{tool_name} requires {required_permission}, an APPROVE_* permission"


def test_all_seeded_tools_are_loadable(connection):
    store = PolicyStore(connection)
    for tool_name in store.list_tool_names():
        policy = store.load(tool_name)
        assert policy.tool_name == tool_name


def test_unknown_tool_raises_not_found(connection):
    with pytest.raises(ToolPolicyNotFoundError):
        PolicyStore(connection).load("nonexistent_tool")


def test_human_only_autonomy_denies_even_when_agent_is_allowed(
    pep: PolicyEnforcementPoint, connection
):
    # Distinct from the apply_remediation case (denied via an empty
    # allowed_agents list before autonomy is even reached) — this proves
    # the HUMAN_ONLY branch itself also denies, for a tool an agent *is*
    # allowed to call.
    connection.execute(
        "INSERT INTO agent_governance.tool_policy "
        "(tool_name, required_permission, autonomy, allowed_agents) "
        "VALUES ('human_only_tool', 'RUN_PIPELINE', 'HUMAN_ONLY', ['AG-1'])"
    )
    decision = pep.decide(
        "human_only_tool",
        AgentId.AG1_PIPELINE_OPERATIONS,
        RoleName.DATA_ENGINEER,
        "sess-1",
        "alice",
    )
    assert decision.outcome == PolicyOutcome.DENY
    assert decision.reason == "HUMAN_ONLY"
