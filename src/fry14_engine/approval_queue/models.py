"""Approval Queue Service (C25) models: `AgentProposal` and the
`ProposalDraft` a tool wrapper builds when the Policy Enforcement Point
escalates a call to `PROPOSE`. See 02-design-document.md §2.11, §3.15.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from fry14_engine.common.enums import Permission


class ProposalType(StrEnum):
    REMEDIATION_RULE = "REMEDIATION_RULE"
    CONTRACT_AMENDMENT = "CONTRACT_AMENDMENT"
    PUBLISH_OVERRIDE = "PUBLISH_OVERRIDE"
    NARRATIVE_RELEASE = "NARRATIVE_RELEASE"
    SOURCE_TICKET = "SOURCE_TICKET"


class ProposalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ProposalDraft(BaseModel):
    """What a tool wrapper hands the PEP when its call resolves to
    `PROPOSE` — everything `AgentProposal` needs except the identity/status
    fields the service itself fills in."""

    model_config = ConfigDict(frozen=True)

    proposal_type: ProposalType
    payload: dict
    rationale: str
    evidence: list[str] = []
    required_permission: Permission
    requires_four_eyes: bool = True


class AgentProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    proposal_id: str
    proposing_agent: str
    session_id: str
    requested_by: str
    proposal_type: ProposalType
    payload: dict
    evidence: list[str] = []
    rationale: str | None = None
    required_permission: Permission
    requires_four_eyes: bool = True
    status: ProposalStatus = ProposalStatus.PENDING
    decided_by: str | None = None
    decision_reason: str | None = None
    created_at: datetime | None = None
    decided_at: datetime | None = None
