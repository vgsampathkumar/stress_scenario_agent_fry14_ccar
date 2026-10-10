"""Approval Queue Service (C25): stores `AgentProposal`s, enforces
four-eyes (the approver must differ from the user who requested the
session) and the approver's own RBAC permission, and records
approve/reject decisions. See 02-design-document.md §3.15.

**Scope note (Phase 9):** per the implementation plan, Phase 9's
deliverable is "tools callable ... with policy and audit enforced, before
any agent exists" — there is no agent yet that produces remediation rules
or contract amendments (that's AG-2, Phase 10), and no applyable service
API for either change type exists in this codebase yet. So `approve()`
here stops at *recording* the governed decision; executing the proposed
change "through the normal service API under the approver's identity" per
§3.15 is deferred to whichever Phase 10+ service actually implements that
change type.
"""

from __future__ import annotations

from datetime import timedelta

import duckdb

from fry14_engine.approval_queue.models import AgentProposal, ProposalDraft, ProposalStatus
from fry14_engine.approval_queue.store import ApprovalQueueStore
from fry14_engine.common.enums import RoleName
from fry14_engine.common.ids import ClockFn, new_record_id, utc_now
from fry14_engine.rbac.service import RbacService


class FourEyesViolationError(Exception):
    pass


class ProposalNotPendingError(Exception):
    pass


class DecisionReasonRequiredError(Exception):
    pass


class ApprovalQueueService:
    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        rbac_service: RbacService | None = None,
        clock: ClockFn = utc_now,
    ) -> None:
        self._store = ApprovalQueueStore(connection)
        self._rbac_service = rbac_service or RbacService()
        self._clock = clock

    def create_proposal(
        self, proposing_agent: str, session_id: str, requested_by: str, draft: ProposalDraft
    ) -> AgentProposal:
        proposal = AgentProposal(
            proposal_id=new_record_id(),
            proposing_agent=proposing_agent,
            session_id=session_id,
            requested_by=requested_by,
            proposal_type=draft.proposal_type,
            payload=draft.payload,
            evidence=draft.evidence,
            rationale=draft.rationale,
            required_permission=draft.required_permission,
            requires_four_eyes=draft.requires_four_eyes,
            status=ProposalStatus.PENDING,
            created_at=self._clock(),
        )
        self._store.write(proposal)
        return self._store.read(proposal.proposal_id)

    def approve(
        self, proposal_id: str, approver_user_id: str, approver_role: RoleName
    ) -> AgentProposal:
        return self._decide(
            proposal_id, approver_user_id, approver_role, ProposalStatus.APPROVED, None
        )

    def reject(
        self, proposal_id: str, approver_user_id: str, approver_role: RoleName, reason: str
    ) -> AgentProposal:
        if not reason:
            raise DecisionReasonRequiredError("Rejecting a proposal requires a reason")
        return self._decide(
            proposal_id, approver_user_id, approver_role, ProposalStatus.REJECTED, reason
        )

    def read(self, proposal_id: str) -> AgentProposal | None:
        return self._store.read(proposal_id)

    def read_pending(self) -> list[AgentProposal]:
        return self._store.read_pending()

    def expire_stale(self, max_age_days: int = 5) -> int:
        """Calendar-day expiry, not business-day — a documented
        simplification of design doc §3.15's "5 business days"."""
        cutoff = self._clock() - timedelta(days=max_age_days)
        return self._store.expire_pending_older_than(cutoff)

    def _decide(
        self,
        proposal_id: str,
        approver_user_id: str,
        approver_role: RoleName,
        status: ProposalStatus,
        reason: str | None,
    ) -> AgentProposal:
        proposal = self._store.read(proposal_id)
        if proposal is None or proposal.status != ProposalStatus.PENDING:
            raise ProposalNotPendingError(f"Proposal {proposal_id!r} is not pending")

        self._rbac_service.require_permission(approver_role, proposal.required_permission)

        if proposal.requires_four_eyes and approver_user_id == proposal.requested_by:
            raise FourEyesViolationError(
                f"Approver {approver_user_id!r} may not decide a proposal they requested"
            )

        decided_at = self._clock()
        self._store.update_decision(proposal_id, status, approver_user_id, reason, decided_at)
        return self._store.read(proposal_id)
