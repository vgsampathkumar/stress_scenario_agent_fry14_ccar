"""Agent Trace Store (C26): append-only writer/reader for
agent_governance.agent_trace_event. See 02-design-document.md §2.11.
"""

from __future__ import annotations

import duckdb

from fry14_engine.agent_trace.models import AgentTraceEvent, AgentTraceEventType

_COLUMNS = [
    "event_id",
    "session_id",
    "agent_id",
    "on_behalf_of",
    "event_type",
    "tool_name",
    "payload_ref",
    "model_id",
    "prompt_template_version",
    "tokens_in",
    "tokens_out",
    "latency_ms",
    "pipeline_run_id",
    "scenario_run_id",
]

_INSERT_SQL = f"""
    INSERT INTO agent_governance.agent_trace_event ({", ".join(_COLUMNS)})
    VALUES ({", ".join("?" for _ in _COLUMNS)})
"""


class AgentTraceStore:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection

    def write(self, event: AgentTraceEvent) -> None:
        self._connection.execute(
            _INSERT_SQL,
            [
                event.event_id,
                event.session_id,
                event.agent_id,
                event.on_behalf_of,
                str(event.event_type),
                event.tool_name,
                event.payload_ref,
                event.model_id,
                event.prompt_template_version,
                event.tokens_in,
                event.tokens_out,
                event.latency_ms,
                event.pipeline_run_id,
                event.scenario_run_id,
            ],
        )

    def read_by_session_id(self, session_id: str) -> list[AgentTraceEvent]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)}, event_timestamp "
            "FROM agent_governance.agent_trace_event "
            "WHERE session_id = ? ORDER BY event_timestamp",
            [session_id],
        ).fetchall()
        columns = [*_COLUMNS, "event_timestamp"]
        events = []
        for row in rows:
            data = dict(zip(columns, row, strict=True))
            data["event_type"] = AgentTraceEventType(data["event_type"])
            events.append(AgentTraceEvent(**data))
        return events

    def count_tool_calls(self, session_id: str, tool_name: str) -> int:
        return self._connection.execute(
            "SELECT COUNT(*) FROM agent_governance.agent_trace_event "
            "WHERE session_id = ? AND tool_name = ? AND event_type = 'TOOL_CALL'",
            [session_id, tool_name],
        ).fetchone()[0]
