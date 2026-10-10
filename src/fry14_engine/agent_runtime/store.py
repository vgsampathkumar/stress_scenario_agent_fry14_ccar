"""Agent Session Store: persists and reads back checkpointed
`AgentSession` state. See schemas/014_agent_runtime.sql.
"""

from __future__ import annotations

import json

import duckdb

from fry14_engine.agent_runtime.models import AgentSession, RunLimits, SessionStatus

_COLUMNS = [
    "session_id",
    "agent_id",
    "on_behalf_of",
    "user_role",
    "model_id",
    "prompt_template_version",
    "status",
    "step_count",
    "tool_call_count",
    "tokens_used",
    "max_steps",
    "max_tool_calls",
    "max_tokens",
    "checkpoint",
]

_INSERT_SQL = f"""
    INSERT INTO agent_governance.agent_session ({", ".join(_COLUMNS)})
    VALUES ({", ".join("?" for _ in _COLUMNS)})
"""


class AgentSessionStore:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection

    def create(self, session: AgentSession) -> None:
        self._connection.execute(
            _INSERT_SQL,
            [
                session.session_id,
                session.agent_id,
                session.on_behalf_of,
                session.user_role,
                session.model_id,
                session.prompt_template_version,
                str(session.status),
                session.step_count,
                session.tool_call_count,
                session.tokens_used,
                session.limits.max_steps,
                session.limits.max_tool_calls,
                session.limits.max_tokens,
                json.dumps(session.checkpoint),
            ],
        )

    def update(self, session: AgentSession) -> None:
        self._connection.execute(
            "UPDATE agent_governance.agent_session "
            "SET status = ?, step_count = ?, tool_call_count = ?, tokens_used = ?, "
            "checkpoint = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE session_id = ?",
            [
                str(session.status),
                session.step_count,
                session.tool_call_count,
                session.tokens_used,
                json.dumps(session.checkpoint),
                session.session_id,
            ],
        )

    def read(self, session_id: str) -> AgentSession | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM agent_governance.agent_session "
            "WHERE session_id = ?",
            [session_id],
        ).fetchone()
        if row is None:
            return None
        data = dict(zip(_COLUMNS, row, strict=True))
        limits = RunLimits(
            max_steps=data.pop("max_steps"),
            max_tool_calls=data.pop("max_tool_calls"),
            max_tokens=data.pop("max_tokens"),
        )
        data["status"] = SessionStatus(data["status"])
        data["checkpoint"] = json.loads(data["checkpoint"]) if data["checkpoint"] else {}
        return AgentSession(**data, limits=limits)
