"""AG-3 Stress Scenario Agent (C20): natural-language request -> draft
`ScenarioSpec` (structured LLM output) -> `build_scenario_spec`
(deterministic validation) -> clarifying question if ambiguous ->
plain-language confirmation -> `run_stress_scenario` -> deterministic
interpretation. The agent never computes PD/LGD/EAD/EL/RWA itself — every
number comes from the Stress Engine (C28, Phase 8). See
02-design-document.md §3.18 and requirements.md §3.2 (AG-3).
"""

from __future__ import annotations

from enum import StrEnum

import duckdb
from pydantic import BaseModel, ConfigDict

from fry14_engine.agent_runtime.models import LlmClient, LlmCompletionRequest
from fry14_engine.agent_runtime.runtime import AgentRuntime
from fry14_engine.common.enums import AgentId, RoleName
from fry14_engine.mcp_server.models import ToolContext
from fry14_engine.mcp_server.server import McpToolServer
from fry14_engine.policy.models import PolicyOutcome
from fry14_engine.reference_data.store import ReferenceDataStore
from fry14_engine.scenario.models import (
    ScenarioReferenceNotFoundError,
    ScenarioTableNotApprovedError,
)
from fry14_engine.scenario.reference_store import ScenarioReferenceStore
from fry14_engine.scenario.run_models import ScenarioRunResult
from fry14_engine.scenario.spec_models import (
    AdhocShock,
    GradeMigration,
    PortfolioScope,
    ScenarioName,
    ScenarioSpec,
)
from fry14_engine.scenario.spec_validator import ScenarioSpecValidationError

_SYSTEM_PROMPT = (
    "You are AG-3, a Stress Scenario specialist. Translate the user's request "
    "into a structured draft. If the base scenario, magnitude, shocked variable, "
    "or portfolio scope is ambiguous, set needs_clarification=true and ask one "
    "specific question instead of guessing. Never invent a stressed PD/LGD/EAD/"
    "EL/RWA value yourself — that is the deterministic Stress Engine's job."
)


class DraftScenarioRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    needs_clarification: bool = False
    clarifying_question: str | None = None
    reporting_period: str = ""
    base_scenario: ScenarioName | None = None
    supervisory_scenario_version: str | None = None
    portfolio_segments: list[str] | None = None
    asset_classes: list[str] | None = None
    credit_grades: list[int] | None = None
    adhoc_shocks: list[AdhocShock] = []
    grade_migration: GradeMigration | None = None
    horizon_quarters: int = 9


class AG3Status(StrEnum):
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    READY_TO_CONFIRM = "READY_TO_CONFIRM"
    REJECTED = "REJECTED"


class AG3DraftResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    status: AG3Status
    clarifying_question: str | None = None
    rejection_reason: str | None = None
    spec: ScenarioSpec | None = None
    plain_language_summary: str | None = None


class RunNotConfirmedError(Exception):
    pass


class StressScenarioAgent:
    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        mcp_server: McpToolServer,
        agent_runtime: AgentRuntime,
    ) -> None:
        self._scenario_reference_store = ScenarioReferenceStore(connection)
        self._reference_data_store = ReferenceDataStore(connection)
        self._server = mcp_server
        self._runtime = agent_runtime

    def draft(
        self,
        on_behalf_of: str,
        user_role: RoleName,
        llm_client: LlmClient,
        nl_request: str,
        clarification_answer: str | None = None,
    ) -> AG3DraftResult:
        session = self._runtime.start_session(
            AgentId.AG3_STRESS_SCENARIO,
            on_behalf_of,
            user_role,
            llm_client.model_id,
            llm_client.prompt_template_version,
        )
        user_prompt = nl_request
        if clarification_answer is not None:
            user_prompt = f"{nl_request}\nClarification answer: {clarification_answer}"

        session, draft_request = self._runtime.complete_structured(
            session,
            llm_client,
            LlmCompletionRequest(system_prompt=_SYSTEM_PROMPT, user_prompt=user_prompt),
            DraftScenarioRequest,
        )

        if draft_request.needs_clarification:
            self._runtime.finish(session)
            return AG3DraftResult(
                session_id=session.session_id,
                status=AG3Status.NEEDS_CLARIFICATION,
                clarifying_question=draft_request.clarifying_question,
            )

        translation_table_version = (
            self._scenario_reference_store.get_active_translation_table().version
        )
        regulatory_parameter_version = self._reference_data_store.get_active().version
        portfolio_scope = PortfolioScope(
            reporting_period=draft_request.reporting_period,
            portfolio_segments=draft_request.portfolio_segments,
            asset_classes=draft_request.asset_classes,
            credit_grades=draft_request.credit_grades,
        )
        ctx = ToolContext(AgentId.AG3_STRESS_SCENARIO, user_role, session.session_id, on_behalf_of)

        try:
            spec_result = self._server.build_scenario_spec(
                ctx,
                portfolio_scope,
                translation_table_version,
                regulatory_parameter_version,
                base_scenario=draft_request.base_scenario,
                supervisory_scenario_version=draft_request.supervisory_scenario_version,
                adhoc_shocks=draft_request.adhoc_shocks,
                grade_migration=draft_request.grade_migration,
                horizon_quarters=draft_request.horizon_quarters,
            )
        except (
            ScenarioSpecValidationError,
            ScenarioTableNotApprovedError,
            ScenarioReferenceNotFoundError,
        ) as exc:
            session = self._runtime.record_tool_call(session)
            self._runtime.finish(session)
            return AG3DraftResult(
                session_id=session.session_id, status=AG3Status.REJECTED, rejection_reason=str(exc)
            )

        session = self._runtime.record_tool_call(session)
        if spec_result.decision.outcome != PolicyOutcome.ALLOW:
            self._runtime.finish(session)
            return AG3DraftResult(
                session_id=session.session_id,
                status=AG3Status.REJECTED,
                rejection_reason=spec_result.decision.reason,
            )

        spec = spec_result.result
        self._runtime.await_confirmation(session)
        return AG3DraftResult(
            session_id=session.session_id,
            status=AG3Status.READY_TO_CONFIRM,
            spec=spec,
            plain_language_summary=self._plain_language_summary(spec),
        )

    def confirm_and_run(
        self,
        session_id: str,
        on_behalf_of: str,
        user_role: RoleName,
        spec: ScenarioSpec,
        base_pipeline_run_id: str,
    ) -> ScenarioRunResult:
        session = self._runtime.read_session(session_id)
        session = self._runtime.resume(session)
        ctx = ToolContext(AgentId.AG3_STRESS_SCENARIO, user_role, session_id, on_behalf_of)

        run_result = self._server.run_stress_scenario(
            ctx, spec, base_pipeline_run_id, already_confirmed=True
        )
        session = self._runtime.record_tool_call(session)
        if run_result.decision.outcome != PolicyOutcome.ALLOW:
            self._runtime.finish(session)
            raise RunNotConfirmedError(run_result.decision.reason)

        self._runtime.finish(session)
        return run_result.result

    @staticmethod
    def _plain_language_summary(spec: ScenarioSpec) -> str:
        scope_bits = []
        if spec.portfolio_scope.portfolio_segments:
            scope_bits.append(f"segments {', '.join(spec.portfolio_scope.portfolio_segments)}")
        if spec.portfolio_scope.asset_classes:
            scope_bits.append(f"asset classes {', '.join(spec.portfolio_scope.asset_classes)}")
        scope_text = (
            " restricted to " + "; ".join(scope_bits)
            if scope_bits
            else " across the full portfolio"
        )

        base = (
            f"the {spec.base_scenario} supervisory scenario ({spec.supervisory_scenario_version})"
            if spec.base_scenario
            else "no supervisory base scenario (ad-hoc shocks only)"
        )
        shocks = f" plus {len(spec.adhoc_shocks)} ad-hoc shock(s)" if spec.adhoc_shocks else ""
        label = (
            "Exploratory — not for regulatory submission"
            if spec.classification == "EXPLORATORY"
            else "Supervisory"
        )
        return (
            f"[{label}] Run {base}{shocks} over {spec.horizon_quarters} quarters{scope_text}, "
            f"using translation table v{spec.translation_table_version}. Confirm to proceed?"
        )

    @staticmethod
    def interpret(result: ScenarioRunResult) -> str:
        """A deterministic summary over the real `ScenarioRunResult` —
        never a narrative with free numbers; AG-4 (with the Grounding
        Checker) owns turning this into prose for release."""
        if not result.comparison_rows:
            return "No loans were in scope for this scenario; nothing to report."

        by_segment: dict[str, float] = {}
        for row in result.comparison_rows:
            by_segment[row.portfolio_segment] = by_segment.get(row.portfolio_segment, 0.0) + float(
                row.delta_el
            )
        top_segment, top_delta_el = max(by_segment.items(), key=lambda kv: abs(kv[1]))

        total_delta_rwa = sum(float(row.delta_rwa) for row in result.comparison_rows)
        rwa_driver = (
            "EAD/drawdown assumptions only (standardized approach: RWA has no PD term)"
            if total_delta_rwa != 0
            else "no change (no drawdown shock reached this portfolio)"
        )

        return (
            f"Classification: {result.classification}. Top contributing segment by EL delta: "
            f"{top_segment} ({top_delta_el:+,.2f}). RWA moved through {rwa_driver}. "
            f"Illustrative 9-quarter projected loss: {result.projected_loss_9q:,.2f}."
        )
