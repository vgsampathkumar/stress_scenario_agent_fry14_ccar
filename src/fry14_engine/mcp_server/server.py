"""MCP Tool Server (C23): typed, thin wrappers over existing service APIs
(C1-C16, C27, C28) — no business logic of its own. Every call passes
through the Policy Enforcement Point (C24) first and is logged to the
Agent Trace Store (C26) via TOOL_CALL/TOOL_RESULT events, bracketing the
POLICY_DECISION event the PEP itself writes. See 02-design-document.md
§3.13.

**Scope note (Phase 9):** of the 13 tools in requirements.md §3.3,
`get_quarantine_summary`, `propose_remediation`, `propose_contract_change`,
and `apply_remediation` are deliberately NOT wrapped here — their ToolPolicy
rows are seeded (so the PEP's policy coverage is complete and testable),
but no backing service exists yet for any of them. `get_quarantine_summary`
is explicitly Phase 10's deliverable per 03-implementation-plan.md; the
other three depend on an agent (AG-2) that doesn't exist yet to produce
meaningful proposals, and there is no "apply a remediation rule" service
API in this codebase at all. Wrapping them now would mean faking a tool
that does nothing real.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Any, TypeVar

import duckdb

from fry14_engine.agent_trace.logger import AgentTraceLogger
from fry14_engine.agent_trace.models import AgentTraceEventType
from fry14_engine.aggregation.gateway import AggregationGateway
from fry14_engine.approval_queue.models import ProposalDraft, ProposalType
from fry14_engine.approval_queue.service import ApprovalQueueService
from fry14_engine.audit.logger import AuditLogger
from fry14_engine.catalog.gateway import DEFAULT_OWNER, CatalogGateway
from fry14_engine.catalog.query_sandbox import QuerySandboxService
from fry14_engine.common.enums import Permission
from fry14_engine.common.metadata import MetadataStamper
from fry14_engine.contracts.models import DataContract
from fry14_engine.contracts.validation_gateway import ValidationGateway
from fry14_engine.ingestion.adapter import IngestionAdapter
from fry14_engine.ingestion.gateway import IngestionGateway
from fry14_engine.ingestion.stamped import StampedRecord
from fry14_engine.mcp_server.models import ToolCallResult, ToolContext
from fry14_engine.pii.governed_models import GovernedLoanRecord
from fry14_engine.pii.hashing_service import PIIHashingService
from fry14_engine.policy.models import PolicyOutcome
from fry14_engine.policy.pep import PolicyEnforcementPoint
from fry14_engine.policy.store import PolicyStore
from fry14_engine.rbac.service import RbacService
from fry14_engine.risk_engine.gateway import RiskCalculationGateway
from fry14_engine.scenario.gateway import StressScenarioGateway
from fry14_engine.scenario.reference_store import ScenarioReferenceStore
from fry14_engine.scenario.spec_models import PortfolioScope, ScenarioSpec
from fry14_engine.scenario.spec_validator import build_scenario_spec

_T = TypeVar("_T")

DEFAULT_PUBLISH_DQ_THRESHOLD_PCT = 98.0


class McpToolServer:
    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        pii_hashing_service: PIIHashingService,
        rbac_service: RbacService | None = None,
        publish_dq_threshold_pct: float = DEFAULT_PUBLISH_DQ_THRESHOLD_PCT,
    ) -> None:
        rbac_service = rbac_service or RbacService()
        self._publish_dq_threshold_pct = publish_dq_threshold_pct

        self._trace_logger = AgentTraceLogger(connection)
        self._approval_queue_service = ApprovalQueueService(connection, rbac_service)
        self._pep = PolicyEnforcementPoint(
            PolicyStore(connection), self._approval_queue_service, self._trace_logger, rbac_service
        )

        self._ingestion_gateway = IngestionGateway(connection)
        self._validation_gateway = ValidationGateway(connection, pii_hashing_service)
        self._risk_calculation_gateway = RiskCalculationGateway(connection)
        self._aggregation_gateway = AggregationGateway(connection)
        self._catalog_gateway = CatalogGateway(connection)
        self._query_sandbox_service = QuerySandboxService(connection, rbac_service)
        self._audit_logger = AuditLogger(connection)
        self._scenario_reference_store = ScenarioReferenceStore(connection)
        self._stress_scenario_gateway = StressScenarioGateway(connection)

    # -- 2.1 Ingestion ----------------------------------------------------

    def ingest_batch(
        self, ctx: ToolContext, adapter: IngestionAdapter, stamper: MetadataStamper
    ) -> ToolCallResult:
        return self._invoke(
            ctx, "ingest_batch", lambda: self._ingestion_gateway.run(adapter, stamper)
        )

    def ingest_event(
        self, ctx: ToolContext, adapter: IngestionAdapter, stamper: MetadataStamper
    ) -> ToolCallResult:
        return self._invoke(
            ctx, "ingest_event", lambda: self._ingestion_gateway.run(adapter, stamper)
        )

    # -- 2.2 Validation -----------------------------------------------------

    def validate_against_contract(
        self,
        ctx: ToolContext,
        stamped_records: list[StampedRecord],
        contract: DataContract,
        pipeline_run_id: str,
    ) -> ToolCallResult:
        return self._invoke(
            ctx,
            "validate_against_contract",
            lambda: self._validation_gateway.run(stamped_records, contract, pipeline_run_id),
        )

    # -- 2.4 Risk calculation + aggregation ----------------------------------

    def calculate_risk_metrics(
        self,
        ctx: ToolContext,
        governed_records: list[GovernedLoanRecord],
        reporting_period: str,
        pipeline_run_id: str,
    ) -> ToolCallResult:
        return self._invoke(
            ctx,
            "calculate_risk_metrics",
            lambda: self._risk_calculation_gateway.run(
                governed_records, reporting_period, pipeline_run_id
            ),
        )

    def aggregate_schedules(self, ctx: ToolContext, pipeline_run_id: str) -> ToolCallResult:
        return self._invoke(
            ctx, "aggregate_schedules", lambda: self._aggregation_gateway.run(pipeline_run_id)
        )

    # -- 2.5 Catalog / publish ------------------------------------------------

    def publish_data_product(
        self,
        ctx: ToolContext,
        data_product_id: str,
        pipeline_run_id: str,
        dq_pass_percentage: float,
        run_completed_at: datetime,
        output_schema_version: str,
        output_schema_effective_date: date,
        owner: str = DEFAULT_OWNER,
    ) -> ToolCallResult:
        breached = dq_pass_percentage < self._publish_dq_threshold_pct
        proposal_draft = None
        if breached:
            proposal_draft = ProposalDraft(
                proposal_type=ProposalType.PUBLISH_OVERRIDE,
                payload={
                    "data_product_id": data_product_id,
                    "pipeline_run_id": pipeline_run_id,
                    "dq_pass_percentage": dq_pass_percentage,
                    "output_schema_version": output_schema_version,
                },
                rationale=(
                    f"DQ pass rate {dq_pass_percentage:.2f}% is below the "
                    f"{self._publish_dq_threshold_pct:.2f}% publish threshold"
                ),
                required_permission=Permission.PUBLISH_DATA_PRODUCT,
            )

        return self._invoke(
            ctx,
            "publish_data_product",
            lambda: self._catalog_gateway.update_after_run(
                data_product_id=data_product_id,
                pipeline_run_id=pipeline_run_id,
                dq_pass_percentage=dq_pass_percentage,
                run_completed_at=run_completed_at,
                output_schema_version=output_schema_version,
                output_schema_effective_date=output_schema_effective_date,
                owner=owner,
            ),
            conditions_context={"dq_pass_rate_below_threshold": breached},
            proposal_draft=proposal_draft,
        )

    def get_catalog_status(self, ctx: ToolContext, data_product_id: str) -> ToolCallResult:
        return self._invoke(
            ctx, "get_catalog_status", lambda: self._catalog_gateway.get_entry(data_product_id)
        )

    def get_lineage(self, ctx: ToolContext, pipeline_run_id: str) -> ToolCallResult:
        return self._invoke(
            ctx, "get_lineage", lambda: self._audit_logger.read_run(pipeline_run_id)
        )

    # -- AG-3 Stress scenario -------------------------------------------------

    def build_scenario_spec(
        self,
        ctx: ToolContext,
        portfolio_scope: PortfolioScope,
        translation_table_version: str,
        regulatory_parameter_version: str,
        **spec_kwargs: Any,
    ) -> ToolCallResult:
        return self._invoke(
            ctx,
            "build_scenario_spec",
            lambda: build_scenario_spec(
                self._scenario_reference_store,
                requested_by=ctx.on_behalf_of,
                portfolio_scope=portfolio_scope,
                translation_table_version=translation_table_version,
                regulatory_parameter_version=regulatory_parameter_version,
                **spec_kwargs,
            ),
        )

    def run_stress_scenario(
        self,
        ctx: ToolContext,
        spec: ScenarioSpec,
        base_pipeline_run_id: str,
        already_confirmed: bool = False,
    ) -> ToolCallResult:
        return self._invoke(
            ctx,
            "run_stress_scenario",
            lambda: self._stress_scenario_gateway.run(spec, base_pipeline_run_id),
            already_confirmed=already_confirmed,
        )

    # -- 2.5 Query sandbox -----------------------------------------------------

    def query_sandbox(
        self, ctx: ToolContext, reporting_period: str, schema_version: str
    ) -> ToolCallResult:
        return self._invoke(
            ctx,
            "query_sandbox",
            lambda: self._query_sandbox_service.query_schedule(
                ctx.user_role, reporting_period, schema_version
            ),
        )

    # -- internals --------------------------------------------------------

    def _invoke(
        self,
        ctx: ToolContext,
        tool_name: str,
        fn: Callable[[], _T],
        conditions_context: dict[str, bool] | None = None,
        already_confirmed: bool = False,
        proposal_draft: ProposalDraft | None = None,
    ) -> ToolCallResult:
        self._trace_logger.log(
            AgentTraceEventType.TOOL_CALL,
            session_id=ctx.session_id,
            agent_id=str(ctx.agent_id),
            on_behalf_of=ctx.on_behalf_of,
            tool_name=tool_name,
        )

        decision = self._pep.decide(
            tool_name,
            ctx.agent_id,
            ctx.user_role,
            ctx.session_id,
            ctx.on_behalf_of,
            conditions_context=conditions_context,
            already_confirmed=already_confirmed,
            proposal_draft=proposal_draft,
        )

        result = fn() if decision.outcome == PolicyOutcome.ALLOW else None

        self._trace_logger.log(
            AgentTraceEventType.TOOL_RESULT,
            session_id=ctx.session_id,
            agent_id=str(ctx.agent_id),
            on_behalf_of=ctx.on_behalf_of,
            tool_name=tool_name,
            payload_ref=f"outcome={decision.outcome}",
        )

        return ToolCallResult(decision=decision, result=result)
