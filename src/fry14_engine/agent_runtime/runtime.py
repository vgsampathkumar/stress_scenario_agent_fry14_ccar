"""Agent Runtime (C17): session lifecycle for every specialist agent —
start, checkpoint each step/tool-call, enforce hard per-session limits,
validate structured LLM output (one retry, then escalate), and
pause-for-confirmation/resume. See 02-design-document.md §3.12.
"""

from __future__ import annotations

from typing import TypeVar

import duckdb
from pydantic import BaseModel, ValidationError

from fry14_engine.agent_runtime.models import (
    AgentSession,
    LlmClient,
    LlmCompletionRequest,
    RunLimits,
    SessionStatus,
    StructuredOutputInvalidError,
)
from fry14_engine.agent_runtime.store import AgentSessionStore
from fry14_engine.agent_trace.logger import AgentTraceLogger
from fry14_engine.agent_trace.models import AgentTraceEventType
from fry14_engine.common.enums import AgentId, RoleName
from fry14_engine.common.ids import new_record_id

_T = TypeVar("_T", bound=BaseModel)

_MAX_STRUCTURED_OUTPUT_ATTEMPTS = 2


class AgentRuntime:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._store = AgentSessionStore(connection)
        self._trace_logger = AgentTraceLogger(connection)

    def start_session(
        self,
        agent_id: AgentId,
        on_behalf_of: str,
        user_role: RoleName,
        model_id: str,
        prompt_template_version: str,
        limits: RunLimits | None = None,
    ) -> AgentSession:
        session = AgentSession(
            session_id=new_record_id(),
            agent_id=str(agent_id),
            on_behalf_of=on_behalf_of,
            user_role=str(user_role),
            model_id=model_id,
            prompt_template_version=prompt_template_version,
            status=SessionStatus.IN_PROGRESS,
            limits=limits or RunLimits(),
        )
        self._store.create(session)
        self._trace_logger.log(
            AgentTraceEventType.USER_REQUEST,
            session_id=session.session_id,
            agent_id=session.agent_id,
            on_behalf_of=on_behalf_of,
            model_id=model_id,
            prompt_template_version=prompt_template_version,
        )
        return session

    def record_step(self, session: AgentSession, checkpoint_update: dict) -> AgentSession:
        if session.status != SessionStatus.IN_PROGRESS:
            return session
        step_count = session.step_count + 1
        status = (
            SessionStatus.LIMIT_REACHED if step_count > session.limits.max_steps else session.status
        )
        updated = session.model_copy(
            update={
                "step_count": step_count,
                "checkpoint": {**session.checkpoint, **checkpoint_update},
                "status": status,
            }
        )
        self._store.update(updated)
        return updated

    def record_tool_call(self, session: AgentSession) -> AgentSession:
        if session.status != SessionStatus.IN_PROGRESS:
            return session
        tool_call_count = session.tool_call_count + 1
        status = (
            SessionStatus.LIMIT_REACHED
            if tool_call_count > session.limits.max_tool_calls
            else session.status
        )
        updated = session.model_copy(update={"tool_call_count": tool_call_count, "status": status})
        self._store.update(updated)
        return updated

    def record_tokens(self, session: AgentSession, tokens_in: int, tokens_out: int) -> AgentSession:
        if session.status != SessionStatus.IN_PROGRESS:
            return session
        tokens_used = session.tokens_used + tokens_in + tokens_out
        status = (
            SessionStatus.LIMIT_REACHED
            if tokens_used > session.limits.max_tokens
            else session.status
        )
        updated = session.model_copy(update={"tokens_used": tokens_used, "status": status})
        self._store.update(updated)
        return updated

    def complete_structured(
        self,
        session: AgentSession,
        llm_client: LlmClient,
        request: LlmCompletionRequest,
        response_schema: type[_T],
    ) -> tuple[AgentSession, _T]:
        """Calls `llm_client.complete()`, validates the result against
        `response_schema`, retries once on a validation failure, then
        raises `StructuredOutputInvalidError` — never silently passes
        through malformed output."""
        last_error: ValidationError | None = None
        for _attempt in range(1, _MAX_STRUCTURED_OUTPUT_ATTEMPTS + 1):
            raw, tokens_in, tokens_out = llm_client.complete(request, response_schema)
            session = self.record_tokens(session, tokens_in, tokens_out)
            try:
                return session, response_schema.model_validate(raw)
            except ValidationError as exc:
                last_error = exc

        session = self._mark_error(session)
        self._trace_logger.log(
            AgentTraceEventType.ERROR,
            session_id=session.session_id,
            agent_id=session.agent_id,
            on_behalf_of=session.on_behalf_of,
            payload_ref=f"STRUCTURED_OUTPUT_INVALID: {last_error}",
        )
        raise StructuredOutputInvalidError(
            f"{response_schema.__name__} failed validation after "
            f"{_MAX_STRUCTURED_OUTPUT_ATTEMPTS} attempts: {last_error}"
        )

    def await_confirmation(self, session: AgentSession) -> AgentSession:
        updated = session.model_copy(update={"status": SessionStatus.AWAITING_CONFIRMATION})
        self._store.update(updated)
        return updated

    def resume(self, session: AgentSession) -> AgentSession:
        updated = session.model_copy(update={"status": SessionStatus.IN_PROGRESS})
        self._store.update(updated)
        return updated

    def finish(
        self, session: AgentSession, status: SessionStatus = SessionStatus.COMPLETED
    ) -> AgentSession:
        updated = session.model_copy(update={"status": status})
        self._store.update(updated)
        return updated

    def read_session(self, session_id: str) -> AgentSession | None:
        return self._store.read(session_id)

    def _mark_error(self, session: AgentSession) -> AgentSession:
        updated = session.model_copy(update={"status": SessionStatus.ERROR})
        self._store.update(updated)
        return updated
