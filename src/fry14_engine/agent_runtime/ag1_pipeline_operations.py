"""AG-1 Pipeline Operations Agent (C18): runs the fixed plan template —
ingest -> validate -> calculate -> aggregate -> check thresholds -> publish
(or propose) -> report — entirely through the MCP Tool Server (tool-only
execution, no direct store/gateway access), under one `AgentRuntime`
session. See 02-design-document.md §3.16 and requirements.md §3.2 (AG-1).

**Scope note:** AG-1's plan is fixed by the design doc itself ("Plan
template: ingest -> validate -> calculate -> aggregate -> check
thresholds -> publish -> report") — there is no open-ended planning
decision for an LLM to make here, so this agent is deterministic
orchestration (same shape as `Orchestrator`, Phase 7) routed through
policy-enforced tools and a checkpointed session, not a live model call.
AG-4's narrative layer (Phase 11) is what turns `RunReport` into prose;
this agent only ever produces the structured report itself.
"""

from __future__ import annotations

from datetime import date

import duckdb
from pydantic import BaseModel, ConfigDict

from fry14_engine.agent_runtime.models import SessionStatus
from fry14_engine.agent_runtime.runtime import AgentRuntime
from fry14_engine.common.enums import AgentId, IngestionChannel, RoleName
from fry14_engine.common.ids import ClockFn, new_pipeline_run_id, utc_now
from fry14_engine.common.metadata import MetadataStamper
from fry14_engine.contracts.models import DataContract
from fry14_engine.mcp_server.models import ToolContext
from fry14_engine.mcp_server.server import McpToolServer
from fry14_engine.orchestrator.models import ChannelSource
from fry14_engine.pii.governed_store import GovernedStore
from fry14_engine.policy.models import PolicyOutcome

MODEL_ID = "deterministic-orchestrator"
PROMPT_TEMPLATE_VERSION = "1.0.0"
DEFAULT_DQ_THRESHOLD_PCT = 98.0


class ToolCallDeniedError(Exception):
    """A tool call AG-1 needs for its fixed plan was denied — almost
    always a misconfigured caller (wrong role/agent), since every step in
    this plan is meant to be AUTONOMOUS for AG-1. Raised rather than
    silently returning a half-finished report."""

    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(f"{stage} denied: {reason}")
        self.stage = stage
        self.reason = reason


class RunReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    pipeline_run_id: str
    session_id: str
    data_product_id: str
    total_count: int
    governed_count: int
    quarantined_count: int
    reason_code_counts: dict[str, int]
    metrics_computed: int
    calculation_exceptions: int
    aggregate_rows: int
    dq_pass_percentage: float
    publish_outcome: str
    publish_reason: str
    publish_proposal_id: str | None = None
    triage_handoff_recommended: bool


class PipelineOperationsAgent:
    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        mcp_server: McpToolServer,
        agent_runtime: AgentRuntime,
        clock: ClockFn = utc_now,
    ) -> None:
        self._governed_store = GovernedStore(connection)
        self._server = mcp_server
        self._runtime = agent_runtime
        self._clock = clock

    def run(
        self,
        on_behalf_of: str,
        user_role: RoleName,
        channels: list[ChannelSource],
        contract: DataContract,
        reporting_period: str,
        data_product_id: str,
        dq_threshold_pct: float = DEFAULT_DQ_THRESHOLD_PCT,
    ) -> RunReport:
        session = self._runtime.start_session(
            AgentId.AG1_PIPELINE_OPERATIONS,
            on_behalf_of,
            user_role,
            MODEL_ID,
            PROMPT_TEMPLATE_VERSION,
        )
        ctx = ToolContext(
            AgentId.AG1_PIPELINE_OPERATIONS, user_role, session.session_id, on_behalf_of
        )
        plan = [
            "ingest",
            "validate",
            "calculate",
            "aggregate",
            "check_thresholds",
            "publish",
            "report",
        ]
        session = self._runtime.record_step(session, {"plan": plan})

        pipeline_run_id = new_pipeline_run_id()
        stamped_records = []
        for channel in channels:
            stamper = MetadataStamper(
                pipeline_run_id=pipeline_run_id,
                source_entity_code=channel.source_entity_code,
                source_system_of_record=channel.source_system_of_record,
                ingestion_channel=channel.adapter.channel,
                clock=self._clock,
            )
            tool = (
                self._server.ingest_batch
                if channel.adapter.channel == IngestionChannel.BATCH
                else self._server.ingest_event
            )
            ingest_result = tool(ctx, channel.adapter, stamper)
            session = self._runtime.record_tool_call(session)
            self._require_allowed(ingest_result, "ingest")
            stamped_records.extend(ingest_result.result.stamped_records)
        session = self._runtime.record_step(session, {"ingestion_done": True})

        validate_result = self._server.validate_against_contract(
            ctx, stamped_records, contract, pipeline_run_id
        )
        session = self._runtime.record_tool_call(session)
        self._require_allowed(validate_result, "validate")
        validation = validate_result.result
        session = self._runtime.record_step(session, {"validation_done": True})

        governed_records = self._governed_store.read_by_pipeline_run_id(pipeline_run_id)
        calc_result = self._server.calculate_risk_metrics(
            ctx, governed_records, reporting_period, pipeline_run_id
        )
        session = self._runtime.record_tool_call(session)
        self._require_allowed(calc_result, "calculate")
        session = self._runtime.record_step(session, {"calculation_done": True})

        agg_result = self._server.aggregate_schedules(ctx, pipeline_run_id)
        session = self._runtime.record_tool_call(session)
        self._require_allowed(agg_result, "aggregate")
        session = self._runtime.record_step(session, {"aggregation_done": True})

        dq_pass_percentage = validation.dq_pass_rate * 100
        breached = dq_pass_percentage < dq_threshold_pct
        session = self._runtime.record_step(
            session, {"dq_pass_percentage": dq_pass_percentage, "threshold_breached": breached}
        )

        publish_result = self._server.publish_data_product(
            ctx,
            data_product_id=data_product_id,
            pipeline_run_id=pipeline_run_id,
            dq_pass_percentage=dq_pass_percentage,
            run_completed_at=self._clock(),
            output_schema_version=agg_result.result.schema_version,
            output_schema_effective_date=date.today(),
        )
        session = self._runtime.record_tool_call(session)
        # Unlike ingest/validate/calculate/aggregate, a DENY here is not
        # necessarily a misconfiguration: `on_behalf_of` may hold
        # RUN_PIPELINE without PUBLISH_DATA_PRODUCT by design (separation
        # of duties — see the RBAC matrix, 02-design-document.md §2.12),
        # so this is reported, not raised.

        session = self._runtime.finish(session, SessionStatus.COMPLETED)

        return RunReport(
            pipeline_run_id=pipeline_run_id,
            session_id=session.session_id,
            data_product_id=data_product_id,
            total_count=validation.total_count,
            governed_count=validation.governed_count,
            quarantined_count=validation.quarantined_count,
            reason_code_counts=validation.reason_code_counts,
            metrics_computed=len(calc_result.result.metrics),
            calculation_exceptions=len(calc_result.result.exceptions),
            aggregate_rows=len(agg_result.result.aggregates),
            dq_pass_percentage=dq_pass_percentage,
            publish_outcome=str(publish_result.decision.outcome),
            publish_reason=publish_result.decision.reason,
            publish_proposal_id=publish_result.decision.proposal_id,
            triage_handoff_recommended=breached,
        )

    @staticmethod
    def _require_allowed(result, stage: str) -> None:
        if result.decision.outcome != PolicyOutcome.ALLOW:
            raise ToolCallDeniedError(stage, result.decision.reason)
