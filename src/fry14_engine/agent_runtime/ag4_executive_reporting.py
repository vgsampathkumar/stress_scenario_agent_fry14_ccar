"""AG-4 Executive Reporting Agent (C21): drafts a narrative as a
`{{token}}`-bound template (never free numbers), resolves every binding
against the real `RunReport` / `ScenarioRunResult` it's citing, and runs
it through the Numeric Grounding Checker (C29). A narrative that fails
grounding is never proposed for release. See 02-design-document.md §3.19
and requirements.md §3.2 (AG-4).
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import duckdb
from pydantic import BaseModel, ConfigDict

from fry14_engine.agent_runtime.ag1_pipeline_operations import RunReport
from fry14_engine.agent_runtime.models import LlmClient, LlmCompletionRequest
from fry14_engine.agent_runtime.runtime import AgentRuntime
from fry14_engine.approval_queue.models import ProposalDraft, ProposalType
from fry14_engine.approval_queue.service import ApprovalQueueService
from fry14_engine.common.enums import AgentId, Permission, RoleName
from fry14_engine.common.ids import new_record_id
from fry14_engine.grounding.checker import GroundingChecker
from fry14_engine.grounding.models import (
    GroundedNarrative,
    GroundingStatus,
    NarrativeApprovalStatus,
)
from fry14_engine.grounding.store import GroundedNarrativeStore
from fry14_engine.scenario.run_models import ScenarioComparisonRow, ScenarioRunResult

_SYSTEM_PROMPT = (
    "You are AG-4, an Executive Reporting specialist. Write the narrative as a "
    "template using {{token}} bindings for every figure — never type a raw "
    "number yourself. State the classification label, any data exceptions, and "
    "limitations explicitly."
)


class NarrativeDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    template_text: str


class NarrativeNotGroundedError(Exception):
    pass


def _format_value(value) -> str:
    if isinstance(value, (Decimal, float, int)) and not isinstance(value, bool):
        return f"{value:,.2f}"
    return str(value)


def _aggregate_by_segment(rows: list[ScenarioComparisonRow]) -> dict[str, dict[str, Decimal]]:
    totals: dict[str, dict[str, Decimal]] = {}
    for row in rows:
        bucket = totals.setdefault(
            row.portfolio_segment,
            {"delta_ead": Decimal("0"), "delta_el": Decimal("0"), "delta_rwa": Decimal("0")},
        )
        bucket["delta_ead"] += row.delta_ead
        bucket["delta_el"] += row.delta_el
        bucket["delta_rwa"] += row.delta_rwa
    return totals


def build_run_report_resolver(run_report: RunReport) -> Callable[[str], str | None]:
    def resolver(token: str) -> str | None:
        if not token.startswith("run:"):
            return None
        run_id, _, attr = token[len("run:") :].partition(".")
        if run_id != run_report.pipeline_run_id or not attr:
            return None
        value = getattr(run_report, attr, None)
        return None if value is None else _format_value(value)

    return resolver


def build_scenario_resolver(result: ScenarioRunResult) -> Callable[[str], str | None]:
    segment_totals = _aggregate_by_segment(result.comparison_rows)

    def resolver(token: str) -> str | None:
        if not token.startswith("scenario:"):
            return None
        run_id, _, attr_path = token[len("scenario:") :].partition(".")
        if run_id != result.scenario_run_id or not attr_path:
            return None
        parts = attr_path.split(".")
        if len(parts) == 3 and parts[0] == "segment":
            _, segment, field = parts
            bucket = segment_totals.get(segment)
            return None if bucket is None or field not in bucket else _format_value(bucket[field])
        if len(parts) == 1 and hasattr(result, parts[0]):
            return _format_value(getattr(result, parts[0]))
        return None

    return resolver


class ExecutiveReportingAgent:
    def __init__(self, connection: duckdb.DuckDBPyConnection, agent_runtime: AgentRuntime) -> None:
        self._grounding_checker = GroundingChecker()
        self._narrative_store = GroundedNarrativeStore(connection)
        self._approval_queue_service = ApprovalQueueService(connection)
        self._runtime = agent_runtime

    def draft_run_narrative(
        self, on_behalf_of: str, user_role: RoleName, llm_client: LlmClient, run_report: RunReport
    ) -> tuple[GroundedNarrative, str | None]:
        return self._draft(
            on_behalf_of,
            user_role,
            llm_client,
            build_run_report_resolver(run_report),
            pipeline_run_id=run_report.pipeline_run_id,
            scenario_run_id=None,
            context_prompt=f"RunReport: {run_report.model_dump_json()}",
        )

    def draft_scenario_narrative(
        self,
        on_behalf_of: str,
        user_role: RoleName,
        llm_client: LlmClient,
        result: ScenarioRunResult,
    ) -> tuple[GroundedNarrative, str | None]:
        return self._draft(
            on_behalf_of,
            user_role,
            llm_client,
            build_scenario_resolver(result),
            pipeline_run_id=None,
            scenario_run_id=result.scenario_run_id,
            context_prompt=(
                f"scenario_run_id={result.scenario_run_id} classification={result.classification} "
                f"projected_loss_9q={result.projected_loss_9q} "
                f"segments={sorted({r.portfolio_segment for r in result.comparison_rows})}"
            ),
        )

    def release(
        self, proposal_id: str, approver_user_id: str, approver_role: RoleName
    ) -> GroundedNarrative:
        approved = self._approval_queue_service.approve(
            proposal_id, approver_user_id, approver_role
        )
        narrative_id = approved.payload["narrative_id"]
        self._narrative_store.update_approval(
            narrative_id, NarrativeApprovalStatus.APPROVED, approver_user_id
        )
        return self._narrative_store.read(narrative_id)

    def _draft(
        self,
        on_behalf_of: str,
        user_role: RoleName,
        llm_client: LlmClient,
        resolver: Callable[[str], str | None],
        pipeline_run_id: str | None,
        scenario_run_id: str | None,
        context_prompt: str,
    ) -> tuple[GroundedNarrative, str | None]:
        session = self._runtime.start_session(
            AgentId.AG4_EXECUTIVE_REPORTING,
            on_behalf_of,
            user_role,
            llm_client.model_id,
            llm_client.prompt_template_version,
        )
        session, draft = self._runtime.complete_structured(
            session,
            llm_client,
            LlmCompletionRequest(system_prompt=_SYSTEM_PROMPT, user_prompt=context_prompt),
            NarrativeDraft,
        )

        grounding_result = self._grounding_checker.check(draft.template_text, resolver)
        narrative = GroundedNarrative(
            narrative_id=new_record_id(),
            session_id=session.session_id,
            pipeline_run_id=pipeline_run_id,
            scenario_run_id=scenario_run_id,
            template_text=draft.template_text,
            rendered_text=grounding_result.rendered_text,
            grounding_status=grounding_result.status,
            approval_status=NarrativeApprovalStatus.DRAFT,
        )
        self._narrative_store.write(narrative)

        if grounding_result.status != GroundingStatus.PASSED:
            self._runtime.finish(session)
            return narrative, None

        proposal = self._approval_queue_service.create_proposal(
            proposing_agent=str(AgentId.AG4_EXECUTIVE_REPORTING),
            session_id=session.session_id,
            requested_by=on_behalf_of,
            draft=ProposalDraft(
                proposal_type=ProposalType.NARRATIVE_RELEASE,
                payload={"narrative_id": narrative.narrative_id},
                rationale="Grounding passed — every figure traces to a stored tool output.",
                required_permission=Permission.APPROVE_NARRATIVE,
            ),
        )
        self._runtime.finish(session)
        return narrative, proposal.proposal_id
