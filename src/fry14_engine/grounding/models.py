"""Numeric Grounding Checker (C29) models: `GroundedNarrative` — a
template with `{{token}}` bindings, its rendered text, and whether every
number in it traces back to a real tool output. See
02-design-document.md §2.11, §3.19 and schemas/013_agent_governance.sql.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class GroundingStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class NarrativeApprovalStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class GroundingResult(BaseModel):
    """What `GroundingChecker.check()` returns — never persisted itself;
    `GroundedNarrative` is the persisted record."""

    model_config = ConfigDict(frozen=True)

    rendered_text: str
    status: GroundingStatus
    unresolved_tokens: list[str] = []
    unbound_numbers: list[str] = []


class GroundedNarrative(BaseModel):
    model_config = ConfigDict(frozen=True)

    narrative_id: str
    session_id: str
    pipeline_run_id: str | None = None
    scenario_run_id: str | None = None
    template_text: str
    rendered_text: str | None = None
    grounding_status: GroundingStatus
    approval_status: NarrativeApprovalStatus = NarrativeApprovalStatus.DRAFT
    released_by: str | None = None
    created_at: datetime | None = None
    released_at: datetime | None = None
