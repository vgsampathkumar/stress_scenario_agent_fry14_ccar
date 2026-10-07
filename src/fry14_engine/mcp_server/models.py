"""MCP Tool Server (C23) models: the identity context every tool call
carries, and the typed envelope every tool call returns. See
02-design-document.md §3.13.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fry14_engine.common.enums import AgentId, RoleName
from fry14_engine.policy.models import PolicyDecision


@dataclass(frozen=True)
class ToolContext:
    """Who is calling a tool, and on whose behalf — resolved by the caller
    (eventually the Agent Runtime, Phase 10) before any tool call. The PEP
    computes effective permission as (user_role's RBAC permissions) ∩
    (agent_id's tool allowlist) ∩ (tool's autonomy level); see
    02-design-document.md §2.12."""

    agent_id: AgentId
    user_role: RoleName
    session_id: str
    on_behalf_of: str  # user_id, or 'SYSTEM_SCHEDULER'


@dataclass(frozen=True)
class ToolCallResult:
    """`result` is only populated when `decision.outcome` is ALLOW — every
    other outcome (CONFIRM_REQUIRED, PROPOSE, DENY) means the underlying
    service API was never called, per design doc §3.14 step 5."""

    decision: PolicyDecision
    result: Any = None
