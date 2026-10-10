"""AG-5 Data Product Concierge Agent (C22): answers natural-language
questions over the governed aggregates by translating them into the
existing typed `query_sandbox` tool call — never raw SQL — and executes
under the **requesting user's own** RBAC permissions (the agent holds
none of its own). See 02-design-document.md §3.20 and requirements.md
§3.2 (AG-5).

**Scope note:** the design doc describes AG-5 "generating SQL" that a SQL
parser then allow-lists. `query_sandbox` (C13, Phase 6) was already built
as a typed, parameterized method with no SQL-accepting surface at all —
structurally stronger than a parsed-and-allow-listed SQL string, since
there is no injection surface to defend at all. This agent keeps that
architecture: the LLM's only job is picking `reporting_period` and
`schema_version` (or refusing), never generating a query string. "Show
the generated query" (AG-5.3) is satisfied by showing the equivalent
typed call.
"""

from __future__ import annotations

import duckdb
from pydantic import BaseModel, ConfigDict

from fry14_engine.agent_runtime.models import LlmClient, LlmCompletionRequest
from fry14_engine.agent_runtime.runtime import AgentRuntime
from fry14_engine.aggregation.models import ScheduleAggregate
from fry14_engine.common.enums import AgentId, RoleName
from fry14_engine.mcp_server.models import ToolContext
from fry14_engine.mcp_server.server import McpToolServer
from fry14_engine.policy.models import PolicyOutcome

_SYSTEM_PROMPT = (
    "You are AG-5, a Data Product Concierge. You may only answer questions "
    "about the published schedule aggregates (EAD/EL/RWA by reporting period, "
    "segment, grade, maturity bucket). You have exactly two parameters "
    "available: reporting_period and schema_version — nothing else. If the "
    "question asks for raw PII, individual borrower data, or any write "
    "operation, set refused=true and give a one-sentence refusal_reason. "
    "Never invent a value for reporting_period or schema_version — if the "
    "user didn't give you one, set refused=true and ask for it instead."
)


class ConciergeQueryRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    refused: bool = False
    refusal_reason: str | None = None
    reporting_period: str | None = None
    schema_version: str | None = None


class ConciergeAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    refused: bool
    message: str | None = None
    generated_query: str | None = None
    rows: list[ScheduleAggregate] = []


class DataProductConciergeAgent:
    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        mcp_server: McpToolServer,
        agent_runtime: AgentRuntime,
    ) -> None:
        self._server = mcp_server
        self._runtime = agent_runtime

    def answer(
        self, on_behalf_of: str, user_role: RoleName, llm_client: LlmClient, nl_question: str
    ) -> ConciergeAnswer:
        session = self._runtime.start_session(
            AgentId.AG5_DATA_PRODUCT_CONCIERGE,
            on_behalf_of,
            user_role,
            llm_client.model_id,
            llm_client.prompt_template_version,
        )
        session, query_request = self._runtime.complete_structured(
            session,
            llm_client,
            LlmCompletionRequest(system_prompt=_SYSTEM_PROMPT, user_prompt=nl_question),
            ConciergeQueryRequest,
        )

        if (
            query_request.refused
            or not query_request.reporting_period
            or not query_request.schema_version
        ):
            self._runtime.finish(session)
            return ConciergeAnswer(
                refused=True,
                message=query_request.refusal_reason
                or "Missing reporting_period or schema_version.",
            )

        ctx = ToolContext(
            AgentId.AG5_DATA_PRODUCT_CONCIERGE, user_role, session.session_id, on_behalf_of
        )
        generated_query = (
            f"query_schedule(reporting_period={query_request.reporting_period!r}, "
            f"schema_version={query_request.schema_version!r})"
        )
        result = self._server.query_sandbox(
            ctx, query_request.reporting_period, query_request.schema_version
        )
        session = self._runtime.record_tool_call(session)
        self._runtime.finish(session)

        if result.decision.outcome != PolicyOutcome.ALLOW:
            return ConciergeAnswer(
                refused=True, message=result.decision.reason, generated_query=generated_query
            )

        return ConciergeAnswer(refused=False, generated_query=generated_query, rows=result.result)
