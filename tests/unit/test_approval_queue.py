"""Approval Queue Service (C25) tests: four-eyes enforcement, approver
RBAC, rejection reasons, and stale-proposal expiry. See
02-design-document.md §3.15.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fry14_engine.approval_queue.models import ProposalDraft, ProposalStatus, ProposalType
from fry14_engine.approval_queue.service import (
    ApprovalQueueService,
    DecisionReasonRequiredError,
    FourEyesViolationError,
    ProposalNotPendingError,
)
from fry14_engine.common.enums import Permission, RoleName
from fry14_engine.db import bootstrap, get_connection
from fry14_engine.rbac.service import PermissionDeniedError


def _draft(**overrides) -> ProposalDraft:
    defaults = dict(
        proposal_type=ProposalType.PUBLISH_OVERRIDE,
        payload={"data_product_id": "dp1"},
        rationale="DQ pass rate below threshold",
        required_permission=Permission.PUBLISH_DATA_PRODUCT,
    )
    defaults.update(overrides)
    return ProposalDraft(**defaults)


@pytest.fixture
def service(tmp_db_path: Path) -> ApprovalQueueService:
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    return ApprovalQueueService(con)


def test_create_proposal_is_pending(service: ApprovalQueueService):
    proposal = service.create_proposal("AG-1", "sess-1", "carol", _draft())
    assert proposal.status == ProposalStatus.PENDING
    assert proposal.requested_by == "carol"
    assert proposal.proposal_id


def test_four_eyes_blocks_self_approval(service: ApprovalQueueService):
    proposal = service.create_proposal("AG-1", "sess-1", "carol", _draft())
    with pytest.raises(FourEyesViolationError):
        service.approve(proposal.proposal_id, "carol", RoleName.REGULATORY_REPORTING)


def test_different_approver_succeeds(service: ApprovalQueueService):
    proposal = service.create_proposal("AG-1", "sess-1", "carol", _draft())
    approved = service.approve(proposal.proposal_id, "dave", RoleName.REGULATORY_REPORTING)
    assert approved.status == ProposalStatus.APPROVED
    assert approved.decided_by == "dave"


def test_approve_requires_the_required_permission(service: ApprovalQueueService):
    proposal = service.create_proposal("AG-1", "sess-1", "carol", _draft())
    with pytest.raises(PermissionDeniedError):
        service.approve(proposal.proposal_id, "dave", RoleName.DATA_ENGINEER)


def test_reject_requires_a_reason(service: ApprovalQueueService):
    proposal = service.create_proposal("AG-1", "sess-1", "carol", _draft())
    with pytest.raises(DecisionReasonRequiredError):
        service.reject(proposal.proposal_id, "dave", RoleName.REGULATORY_REPORTING, "")


def test_reject_records_the_reason(service: ApprovalQueueService):
    proposal = service.create_proposal("AG-1", "sess-1", "carol", _draft())
    rejected = service.reject(
        proposal.proposal_id, "dave", RoleName.REGULATORY_REPORTING, "insufficient evidence"
    )
    assert rejected.status == ProposalStatus.REJECTED
    assert rejected.decision_reason == "insufficient evidence"


def test_cannot_decide_an_already_decided_proposal(service: ApprovalQueueService):
    proposal = service.create_proposal("AG-1", "sess-1", "carol", _draft())
    service.approve(proposal.proposal_id, "dave", RoleName.REGULATORY_REPORTING)
    with pytest.raises(ProposalNotPendingError):
        service.approve(proposal.proposal_id, "erin", RoleName.REGULATORY_REPORTING)


def test_unknown_proposal_raises_not_pending(service: ApprovalQueueService):
    with pytest.raises(ProposalNotPendingError):
        service.approve("nonexistent-id", "dave", RoleName.REGULATORY_REPORTING)


def test_four_eyes_not_enforced_when_draft_opts_out(service: ApprovalQueueService):
    proposal = service.create_proposal("AG-1", "sess-1", "carol", _draft(requires_four_eyes=False))
    approved = service.approve(proposal.proposal_id, "carol", RoleName.REGULATORY_REPORTING)
    assert approved.status == ProposalStatus.APPROVED


def test_read_pending_excludes_decided_proposals(service: ApprovalQueueService):
    pending_proposal = service.create_proposal("AG-1", "sess-1", "carol", _draft())
    decided_proposal = service.create_proposal("AG-1", "sess-2", "carol", _draft())
    service.approve(decided_proposal.proposal_id, "dave", RoleName.REGULATORY_REPORTING)

    pending_ids = {p.proposal_id for p in service.read_pending()}
    assert pending_ids == {pending_proposal.proposal_id}


def test_expire_stale_marks_old_pending_proposals_expired(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    now = datetime(2026, 6, 1, tzinfo=UTC)
    service = ApprovalQueueService(con, clock=lambda: now)
    old_proposal = service.create_proposal("AG-1", "sess-1", "carol", _draft())

    later_clock = lambda: now + timedelta(days=6)  # noqa: E731
    later_service = ApprovalQueueService(con, clock=later_clock)
    expired_count = later_service.expire_stale(max_age_days=5)

    assert expired_count == 1
    assert later_service._store.read(old_proposal.proposal_id).status == ProposalStatus.EXPIRED


def test_expire_stale_leaves_recent_proposals_pending(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    now = datetime(2026, 6, 1, tzinfo=UTC)
    service = ApprovalQueueService(con, clock=lambda: now)
    proposal = service.create_proposal("AG-1", "sess-1", "carol", _draft())

    expired_count = service.expire_stale(max_age_days=5)

    assert expired_count == 0
    assert service._store.read(proposal.proposal_id).status == ProposalStatus.PENDING
