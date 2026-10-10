"""Agent Runtime (C17) models: the checkpointed session state every
specialist agent (AG-1..AG-5) runs inside, hard per-session limits, and the
`LlmClient` protocol specialists call through for structured output. See
02-design-document.md §3.12.

**Scope note:** implemented as a plain, dependency-free Python state
machine rather than a specific graph framework (e.g. LangGraph) — the
design doc's own "Technology Considerations" section lists that as
non-binding, and the `agentic` extra in pyproject.toml is explicitly not
installed/exercised yet. `LlmClient` is a `Protocol`: no concrete
implementation (real or fake) lives in `src/` — a production
implementation (e.g. wrapping the `anthropic` SDK) is deferred until API
credentials are actually in scope; tests supply their own fake.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict


class SessionStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    COMPLETED = "COMPLETED"
    LIMIT_REACHED = "LIMIT_REACHED"
    ERROR = "ERROR"


class RunLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_steps: int = 20
    max_tool_calls: int = 30
    max_tokens: int = 50_000


class AgentSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    agent_id: str
    on_behalf_of: str
    user_role: str
    model_id: str
    prompt_template_version: str
    status: SessionStatus = SessionStatus.IN_PROGRESS
    step_count: int = 0
    tool_call_count: int = 0
    tokens_used: int = 0
    limits: RunLimits = RunLimits()
    checkpoint: dict[str, Any] = {}


class StructuredOutputInvalidError(Exception):
    """Raised when a specialist's structured output still fails schema
    validation after one retry — escalated as an error, never passed on,
    per design doc §3.12."""


class LlmCompletionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    system_prompt: str
    user_prompt: str


class LlmClient(Protocol):
    """A pinned model identifier + prompt template version, and one
    structured-completion method. `complete()` returns the raw parsed JSON
    (a dict, not yet schema-validated — validation and the one-retry rule
    live in `AgentRuntime.complete_structured`) plus token counts."""

    model_id: str
    prompt_template_version: str

    def complete(
        self, request: LlmCompletionRequest, response_schema: type[BaseModel]
    ) -> tuple[dict[str, Any], int, int]:
        """Returns (raw_structured_output, tokens_in, tokens_out)."""
        ...
