"""Policy Store: loads `ToolPolicy` config from
agent_governance.tool_policy (+ its conditions) into an in-memory object,
mirroring `ReferenceDataStore`'s load pattern. See 02-design-document.md
§3.14.
"""

from __future__ import annotations

import duckdb

from fry14_engine.common.enums import AgentId, AutonomyLevel, Permission
from fry14_engine.policy.models import ToolPolicy, ToolPolicyCondition, ToolPolicyNotFoundError


class PolicyStore:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection

    def list_tool_names(self) -> list[str]:
        rows = self._connection.execute(
            "SELECT tool_name FROM agent_governance.tool_policy ORDER BY tool_name"
        ).fetchall()
        return [row[0] for row in rows]

    def load(self, tool_name: str) -> ToolPolicy:
        header = self._connection.execute(
            "SELECT required_permission, autonomy, allowed_agents, max_calls_per_session, version "
            "FROM agent_governance.tool_policy WHERE tool_name = ?",
            [tool_name],
        ).fetchone()
        if header is None:
            raise ToolPolicyNotFoundError(f"No ToolPolicy for tool {tool_name!r}")
        required_permission, autonomy, allowed_agents, max_calls_per_session, version = header

        condition_rows = self._connection.execute(
            "SELECT condition_id, expression, escalate_to "
            "FROM agent_governance.tool_policy_condition "
            "WHERE tool_name = ? ORDER BY condition_id",
            [tool_name],
        ).fetchall()

        return ToolPolicy(
            tool_name=tool_name,
            required_permission=Permission(required_permission),
            autonomy=AutonomyLevel(autonomy),
            allowed_agents=[AgentId(a) for a in (allowed_agents or [])],
            max_calls_per_session=max_calls_per_session,
            conditions=[
                ToolPolicyCondition(
                    condition_id=condition_id,
                    expression=expression,
                    escalate_to=AutonomyLevel(escalate_to),
                )
                for condition_id, expression, escalate_to in condition_rows
            ],
            version=version,
        )
