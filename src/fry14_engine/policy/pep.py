"""Policy Enforcement Point (C24): the deterministic decision procedure
every MCP tool call passes through before execution. Plain code — it never
calls an LLM. See 02-design-document.md §3.14.

Decision procedure (design doc order):
1. Caller already resolved the requesting user/agent (passed in).
2. Deny if the agent isn't in the tool's `allowed_agents`.
3. Deny if the user lacks `required_permission`.
4. Evaluate `conditions` against a caller-supplied `conditions_context`
   (named booleans, never an evaluated expression string — see
   `ToolPolicyCondition`'s own docstring for why) to resolve the
   *effective* autonomy level.
5. Act on the effective autonomy level (AUTONOMOUS/CONFIRM/PROPOSE/
   HUMAN_ONLY/PROHIBITED).
6. Deny if the session has hit `max_calls_per_session` for this tool.
7. Always write a POLICY_DECISION trace event, allow or deny.
"""

from __future__ import annotations

from fry14_engine.agent_trace.logger import AgentTraceLogger
from fry14_engine.agent_trace.models import AgentTraceEventType
from fry14_engine.approval_queue.models import ProposalDraft
from fry14_engine.approval_queue.service import ApprovalQueueService
from fry14_engine.common.enums import AgentId, AutonomyLevel, RoleName
from fry14_engine.policy.models import PolicyDecision, PolicyOutcome, ToolPolicy
from fry14_engine.policy.store import PolicyStore
from fry14_engine.rbac.service import PermissionDeniedError, RbacService


class ProposalDraftRequiredError(Exception):
    """Raised when a tool call resolves to PROPOSE but the caller didn't
    supply a `ProposalDraft` — a config/caller bug, not a policy outcome,
    so it's a hard failure rather than a silent DENY."""


class PolicyEnforcementPoint:
    def __init__(
        self,
        policy_store: PolicyStore,
        approval_queue_service: ApprovalQueueService,
        agent_trace_logger: AgentTraceLogger,
        rbac_service: RbacService | None = None,
    ) -> None:
        self._policy_store = policy_store
        self._approval_queue_service = approval_queue_service
        self._agent_trace_logger = agent_trace_logger
        self._rbac_service = rbac_service or RbacService()

    def decide(
        self,
        tool_name: str,
        agent_id: AgentId,
        user_role: RoleName,
        session_id: str,
        on_behalf_of: str,
        conditions_context: dict[str, bool] | None = None,
        already_confirmed: bool = False,
        proposal_draft: ProposalDraft | None = None,
    ) -> PolicyDecision:
        conditions_context = conditions_context or {}
        policy = self._policy_store.load(tool_name)

        decision = self._resolve(
            policy,
            agent_id,
            user_role,
            session_id,
            on_behalf_of,
            conditions_context,
            already_confirmed,
            proposal_draft,
        )

        self._agent_trace_logger.log(
            AgentTraceEventType.POLICY_DECISION,
            session_id=session_id,
            agent_id=str(agent_id),
            on_behalf_of=on_behalf_of,
            tool_name=tool_name,
            payload_ref=f"outcome={decision.outcome};autonomy={decision.autonomy};reason={decision.reason}",
        )
        return decision

    def _resolve(
        self,
        policy: ToolPolicy,
        agent_id: AgentId,
        user_role: RoleName,
        session_id: str,
        on_behalf_of: str,
        conditions_context: dict[str, bool],
        already_confirmed: bool,
        proposal_draft: ProposalDraft | None,
    ) -> PolicyDecision:
        if agent_id not in policy.allowed_agents:
            return PolicyDecision(
                tool_name=policy.tool_name,
                outcome=PolicyOutcome.DENY,
                autonomy=policy.autonomy,
                reason=f"AGENT_NOT_ALLOWED: {agent_id} may not call {policy.tool_name!r}",
            )

        try:
            self._rbac_service.require_permission(user_role, policy.required_permission)
        except PermissionDeniedError:
            return PolicyDecision(
                tool_name=policy.tool_name,
                outcome=PolicyOutcome.DENY,
                autonomy=policy.autonomy,
                reason=f"PERMISSION_DENIED: {user_role} lacks {policy.required_permission}",
            )

        effective_autonomy = policy.autonomy
        for condition in policy.conditions:
            if conditions_context.get(condition.expression):
                effective_autonomy = condition.escalate_to
                break

        if policy.max_calls_per_session is not None:
            call_count = self._agent_trace_logger.count_tool_calls(session_id, policy.tool_name)
            if call_count >= policy.max_calls_per_session:
                return PolicyDecision(
                    tool_name=policy.tool_name,
                    outcome=PolicyOutcome.DENY,
                    autonomy=effective_autonomy,
                    reason=(
                        f"SESSION_LIMIT_EXCEEDED: {policy.tool_name!r} already called "
                        f"{call_count} times this session (max {policy.max_calls_per_session})"
                    ),
                )

        if effective_autonomy == AutonomyLevel.AUTONOMOUS:
            return PolicyDecision(
                tool_name=policy.tool_name,
                outcome=PolicyOutcome.ALLOW,
                autonomy=effective_autonomy,
                reason="AUTONOMOUS",
            )

        if effective_autonomy == AutonomyLevel.CONFIRM:
            if already_confirmed:
                return PolicyDecision(
                    tool_name=policy.tool_name,
                    outcome=PolicyOutcome.ALLOW,
                    autonomy=effective_autonomy,
                    reason="CONFIRMED",
                )
            return PolicyDecision(
                tool_name=policy.tool_name,
                outcome=PolicyOutcome.CONFIRM_REQUIRED,
                autonomy=effective_autonomy,
                reason="CONFIRM_REQUIRED",
            )

        if effective_autonomy == AutonomyLevel.PROPOSE:
            if proposal_draft is None:
                raise ProposalDraftRequiredError(
                    f"{policy.tool_name!r} resolved to PROPOSE but no ProposalDraft was supplied"
                )
            proposal = self._approval_queue_service.create_proposal(
                proposing_agent=str(agent_id),
                session_id=session_id,
                requested_by=on_behalf_of,
                draft=proposal_draft,
            )
            return PolicyDecision(
                tool_name=policy.tool_name,
                outcome=PolicyOutcome.PROPOSE,
                autonomy=effective_autonomy,
                reason="PROPOSED",
                proposal_id=proposal.proposal_id,
            )

        # HUMAN_ONLY or PROHIBITED
        return PolicyDecision(
            tool_name=policy.tool_name,
            outcome=PolicyOutcome.DENY,
            autonomy=effective_autonomy,
            reason=str(effective_autonomy),
        )
