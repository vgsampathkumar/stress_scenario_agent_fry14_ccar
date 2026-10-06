"""Policy Enforcement Point (C24) models: `ToolPolicy` (versioned config)
and the `PolicyDecision` the PEP returns for every tool call. See
02-design-document.md §2.11, §3.14 and schemas/013_agent_governance.sql.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from fry14_engine.common.enums import AgentId, AutonomyLevel, Permission


class ToolPolicyNotFoundError(Exception):
    pass


class PolicyOutcome(StrEnum):
    """What the calling tool wrapper should actually do, derived from the
    resolved `AutonomyLevel` — not a 1:1 rename: `CONFIRM` splits into
    `ALLOW` (already confirmed) or `CONFIRM_REQUIRED`, and both
    `HUMAN_ONLY` and `PROHIBITED` collapse to `DENY` (the reason string
    still distinguishes them)."""

    ALLOW = "ALLOW"
    CONFIRM_REQUIRED = "CONFIRM_REQUIRED"
    PROPOSE = "PROPOSE"
    DENY = "DENY"


class ToolPolicyCondition(BaseModel):
    model_config = ConfigDict(frozen=True)

    condition_id: int
    # A named boolean fact the caller supplies via `conditions_context`
    # (e.g. "dq_pass_rate_below_threshold") — deliberately NOT a free-form
    # expression evaluated by this code. The PEP "never calls an LLM" and
    # must never `eval()` untrusted strings either; see design doc §3.14's
    # own description of it as "plain code."
    expression: str
    escalate_to: AutonomyLevel


class ToolPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    required_permission: Permission
    autonomy: AutonomyLevel
    allowed_agents: list[AgentId]
    max_calls_per_session: int | None = None
    conditions: list[ToolPolicyCondition] = []
    version: str = "1.0.0"


class PolicyDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    outcome: PolicyOutcome
    autonomy: AutonomyLevel
    reason: str
    proposal_id: str | None = None
