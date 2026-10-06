"""Agent Trace Store (C26) models: `AgentTraceEvent`, the append-only
record of every agent-session step — user requests, plans, tool calls and
results, policy decisions, proposals, approvals, responses, grounding
checks, and errors. See 02-design-document.md §2.11 and
schemas/013_agent_governance.sql.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class AgentTraceEventType(StrEnum):
    USER_REQUEST = "USER_REQUEST"
    PLAN = "PLAN"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    POLICY_DECISION = "POLICY_DECISION"
    PROPOSAL = "PROPOSAL"
    APPROVAL = "APPROVAL"
    RESPONSE = "RESPONSE"
    GROUNDING_CHECK = "GROUNDING_CHECK"
    ERROR = "ERROR"


class AgentTraceEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    session_id: str
    agent_id: str
    on_behalf_of: str  # user_id, or 'SYSTEM_SCHEDULER' for unattended runs
    event_type: AgentTraceEventType
    # Not in the design doc's own AgentTraceEvent field list — added so the
    # Policy Enforcement Point can enforce ToolPolicy.max_calls_per_session
    # by querying trace events directly, without parsing payload_ref.
    tool_name: str | None = None
    payload_ref: str | None = None  # pointer + hash, or an inline PII-free JSON blob
    model_id: str | None = None
    prompt_template_version: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int | None = None
    pipeline_run_id: str | None = None
    scenario_run_id: str | None = None
    event_timestamp: datetime | None = None
