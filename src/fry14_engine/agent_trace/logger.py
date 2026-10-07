"""Agent Trace Logger: the convenience entry point the Policy Enforcement
Point, MCP Tool Server, and (eventually) the Agent Runtime use to record
trace events — mirrors `AuditLogger`'s role for pipeline runs. See
02-design-document.md §2.11, §3.12.
"""

from __future__ import annotations

import duckdb

from fry14_engine.agent_trace.models import AgentTraceEvent, AgentTraceEventType
from fry14_engine.agent_trace.store import AgentTraceStore
from fry14_engine.common.ids import new_record_id


class AgentTraceLogger:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._store = AgentTraceStore(connection)

    def log(
        self,
        event_type: AgentTraceEventType,
        session_id: str,
        agent_id: str,
        on_behalf_of: str,
        tool_name: str | None = None,
        payload_ref: str | None = None,
        model_id: str | None = None,
        prompt_template_version: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        latency_ms: int | None = None,
        pipeline_run_id: str | None = None,
        scenario_run_id: str | None = None,
    ) -> None:
        self._store.write(
            AgentTraceEvent(
                event_id=new_record_id(),
                session_id=session_id,
                agent_id=agent_id,
                on_behalf_of=on_behalf_of,
                event_type=event_type,
                tool_name=tool_name,
                payload_ref=payload_ref,
                model_id=model_id,
                prompt_template_version=prompt_template_version,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
                pipeline_run_id=pipeline_run_id,
                scenario_run_id=scenario_run_id,
            )
        )

    def read_session(self, session_id: str) -> list[AgentTraceEvent]:
        """Reconstruct every recorded step of an agent session, in order."""
        return self._store.read_by_session_id(session_id)

    def count_tool_calls(self, session_id: str, tool_name: str) -> int:
        return self._store.count_tool_calls(session_id, tool_name)
