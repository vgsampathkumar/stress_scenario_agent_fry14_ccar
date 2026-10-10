"""End-to-end demo of the agentic layer (Phases 9-11): all five agents,
run back to back through the real `McpToolServer`/`PolicyEnforcementPoint`
/`AgentRuntime` stack — nothing here is mocked except the LLM itself (no
model credentials are wired into this repo yet; see
`agent_runtime/models.py`'s own scope note on `LlmClient`).

**This is the "Agent UI" deliverable's CLI form.** Per the design doc's
own allowance for Phase 6 (an "Operational Dashboard" can be a documented
CLI report rather than a web UI), this demo plays the same role for the
conversational workspace / Approval Queue / Scenario Comparison views
requirements.md §3.6 describes: it prints the plan, every tool call's
outcome, the approval queue's state, and a scenario comparison table — the
same information a UI would render, just as text. `fry14_engine.ui.app`
(Phase 11, `pip install -e ".[ui]"`) now also renders this same data —
`run_agent_demo()` plus the Approval Queue and Agent Trace stores — as a
Streamlit dashboard, with live approve/reject wired to the real
`ApprovalQueueService`.

`ScriptedLlmClient` returns fixed, illustrative structured responses — it
is not a real model call. It exists only so this command can run with no
API credentials, exactly like `demo.py`'s hardcoded dev-only hash key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from fry14_engine.agent_runtime.ag1_pipeline_operations import PipelineOperationsAgent, RunReport
from fry14_engine.agent_runtime.ag2_data_quality_triage import (
    DataQualityTriageAgent,
    ProposalTypeChoice,
    RemediationAction,
    RootCauseHypothesis,
    RootCauseHypothesisList,
)
from fry14_engine.agent_runtime.ag3_stress_scenario import DraftScenarioRequest, StressScenarioAgent
from fry14_engine.agent_runtime.ag4_executive_reporting import (
    ExecutiveReportingAgent,
    NarrativeDraft,
)
from fry14_engine.agent_runtime.ag5_data_product_concierge import (
    ConciergeQueryRequest,
    DataProductConciergeAgent,
)
from fry14_engine.agent_runtime.runtime import AgentRuntime
from fry14_engine.approval_queue.models import AgentProposal
from fry14_engine.approval_queue.service import ApprovalQueueService
from fry14_engine.common.enums import IngestionChannel, RoleName
from fry14_engine.contracts.registry import ContractRegistry
from fry14_engine.db import REPO_ROOT, bootstrap, get_connection
from fry14_engine.grounding.models import GroundedNarrative
from fry14_engine.ingestion.adapter import IngestionAdapter, IngestionBatch
from fry14_engine.mcp_server.server import McpToolServer
from fry14_engine.orchestrator.models import ChannelSource
from fry14_engine.pii.hashing_service import PIIHashingService
from fry14_engine.scenario.models import ScenarioName
from fry14_engine.scenario.run_models import ScenarioRunResult
from fry14_engine.synthetic.generator import (
    generate_loan_records,
    generate_schema_change_drops_credit_score_batch,
)

DEFAULT_AGENT_DEMO_DB_PATH = REPO_ROOT / "data" / "agent_demo.duckdb"
_DEMO_INSECURE_DEFAULT_HASH_KEY = "dev-only-insecure-default-key-do-not-use-in-production"


class _FixedBatchAdapter(IngestionAdapter):
    channel = IngestionChannel.BATCH
    source_system_of_record = "CORE_LOAN_SYSTEM"

    def __init__(self, records: list[dict]) -> None:
        self._records = records

    def read(self) -> IngestionBatch:
        batch = IngestionBatch()
        for payload in self._records:
            self._normalize_into(payload, batch)
        return batch


class ScriptedLlmClient:
    """Returns one fixed, schema-valid structured response — a scripted
    stand-in for a real model call. See this module's own docstring."""

    model_id = "scripted-demo-client"
    prompt_template_version = "1.0.0"

    def __init__(self, response_model: BaseModel) -> None:
        self._response_model = response_model

    def complete(self, request: Any, response_schema: type) -> tuple[dict, int, int]:
        return self._response_model.model_dump(mode="json"), 0, 0


@dataclass
class AgentDemoResult:
    db_path: Path
    run_report: RunReport
    quarantine_proposals: list[AgentProposal]
    approved_proposals: list[AgentProposal]
    reprocessed_count: int
    run_narrative: GroundedNarrative
    run_narrative_released: bool
    scenario_result: ScenarioRunResult
    scenario_plain_language_summary: str
    scenario_interpretation: str
    scenario_narrative: GroundedNarrative
    concierge_answer_row_count: int
    concierge_generated_query: str | None
    pending_proposals: list[AgentProposal] = field(default_factory=list)
    run_session_id: str = ""
    scenario_session_id: str = ""


def run_agent_demo(
    db_path: Path | str = DEFAULT_AGENT_DEMO_DB_PATH,
    count: int = 20,
    seed: int = 7,
) -> AgentDemoResult:
    db_path = Path(db_path)
    bootstrap(db_path)
    connection = get_connection(db_path)

    contract = ContractRegistry(
        REPO_ROOT / "config" / "contracts", connection=connection
    ).get_active("commercial_loan")
    pii_hashing_service = PIIHashingService(_DEMO_INSECURE_DEFAULT_HASH_KEY)
    server = McpToolServer(connection, pii_hashing_service)
    runtime = AgentRuntime(connection)
    approval_queue = ApprovalQueueService(connection)

    # -- AG-1: ingest a batch with one labeled, attributable defect ----------
    good = generate_loan_records(count=count, bad_record_rate=0.0, seed=seed)
    bad = generate_schema_change_drops_credit_score_batch(
        count=max(1, count // 5),
        source_system_of_record="CORE_LOAN_SYSTEM",
        seed=seed + 1,
        start_index=count,
    )
    channel = ChannelSource(
        adapter=_FixedBatchAdapter(good + bad),
        source_entity_code="ENTITY_001",
        source_system_of_record="CORE_LOAN_SYSTEM",
    )
    ag1 = PipelineOperationsAgent(connection, server, runtime)
    run_report = ag1.run(
        "scheduler", RoleName.ADMIN, [channel], contract, "2026-06", "fry14.schedule"
    )

    # -- AG-2: triage the quarantine AG-1 just produced -----------------------
    ag2 = DataQualityTriageAgent(connection, server, runtime)
    hypothesis = RootCauseHypothesis(
        reason_code="MISSING_CREDIT_SCORE",
        cluster_key="source_system=CORE_LOAN_SYSTEM",
        root_cause="CORE_LOAN_SYSTEM's schema change dropped credit_score",
        citation="100% of this cluster is null for credit_score, all from CORE_LOAN_SYSTEM",
        proposal_type=ProposalTypeChoice.REMEDIATION_RULE,
        rationale="Default missing credit_score to 650 pending the upstream fix",
        remediation_field="credit_score",
        remediation_action=RemediationAction.SET_DEFAULT,
        remediation_value=650,
    )
    triage_llm = ScriptedLlmClient(RootCauseHypothesisList(hypotheses=[hypothesis]))
    quarantine_proposals = ag2.run("data.engineer", RoleName.DATA_ENGINEER, triage_llm)

    approved_proposals = []
    reprocessed_count = 0
    for proposal in quarantine_proposals:
        approved = approval_queue.approve(proposal.proposal_id, "data.lead", RoleName.DATA_ENGINEER)
        approved_proposals.append(approved)
        count_reprocessed, _still_quarantined = ag2.reprocess_after_approval(approved, contract)
        reprocessed_count += count_reprocessed

    # -- AG-4: narrative over the run itself ----------------------------------
    ag4 = ExecutiveReportingAgent(connection, runtime)
    run_narrative_template = (
        f"[Exploratory - illustrative demo data] The run governed "
        f"{{{{run:{run_report.pipeline_run_id}.governed_count}}}} of "
        f"{{{{run:{run_report.pipeline_run_id}.total_count}}}} records "
        f"({{{{run:{run_report.pipeline_run_id}.dq_pass_percentage}}}}% DQ pass rate)."
    )
    run_narrative, run_proposal_id = ag4.draft_run_narrative(
        "scheduler",
        RoleName.REGULATORY_REPORTING,
        ScriptedLlmClient(NarrativeDraft(template_text=run_narrative_template)),
        run_report,
    )
    run_narrative_released = False
    if run_proposal_id:
        ag4.release(run_proposal_id, "reg.reporting.lead", RoleName.REGULATORY_REPORTING)
        run_narrative_released = True

    # -- AG-3: stress scenario request -----------------------------------------
    ag3 = StressScenarioAgent(connection, server, runtime)
    scenario_draft = DraftScenarioRequest(
        reporting_period="2026-06",
        base_scenario=ScenarioName.SEVERELY_ADVERSE,
        supervisory_scenario_version="FED-2026",
    )
    drafted = ag3.draft(
        "risk.analyst",
        RoleName.FINANCE,
        ScriptedLlmClient(scenario_draft),
        "Run Severely Adverse on the book",
    )
    scenario_result = ag3.confirm_and_run(
        drafted.session_id,
        "risk.analyst",
        RoleName.FINANCE,
        drafted.spec,
        run_report.pipeline_run_id,
    )
    scenario_interpretation = StressScenarioAgent.interpret(scenario_result)

    # -- AG-4: narrative over the scenario result -------------------------------
    scenario_segment = (
        scenario_result.comparison_rows[0].portfolio_segment
        if scenario_result.comparison_rows
        else None
    )
    scenario_narrative_template = (
        f"[Exploratory - illustrative demo data] Under Severely Adverse, projected "
        f"nine-quarter loss is "
        f"{{{{scenario:{scenario_result.scenario_run_id}.projected_loss_9q}}}}."
    )
    if scenario_segment:
        scenario_narrative_template += (
            f" {scenario_segment} EL moved by "
            f"{{{{scenario:{scenario_result.scenario_run_id}.segment.{scenario_segment}.delta_el}}}}."
        )
    scenario_narrative, _scenario_proposal_id = ag4.draft_scenario_narrative(
        "risk.analyst",
        RoleName.RISK,
        ScriptedLlmClient(NarrativeDraft(template_text=scenario_narrative_template)),
        scenario_result,
    )

    # -- AG-5: concierge question -----------------------------------------------
    ag5 = DataProductConciergeAgent(connection, server, runtime)
    concierge_response = ConciergeQueryRequest(reporting_period="2026-06", schema_version="1.0.0")
    concierge_answer = ag5.answer(
        "finance.analyst",
        RoleName.FINANCE,
        ScriptedLlmClient(concierge_response),
        "What was total RWA last quarter?",
    )

    pending_proposals = approval_queue.read_pending()

    connection.close()

    return AgentDemoResult(
        db_path=db_path,
        run_report=run_report,
        quarantine_proposals=quarantine_proposals,
        approved_proposals=approved_proposals,
        reprocessed_count=reprocessed_count,
        run_narrative=run_narrative,
        run_narrative_released=run_narrative_released,
        scenario_result=scenario_result,
        scenario_plain_language_summary=drafted.plain_language_summary or "",
        scenario_interpretation=scenario_interpretation,
        scenario_narrative=scenario_narrative,
        concierge_answer_row_count=len(concierge_answer.rows),
        concierge_generated_query=concierge_answer.generated_query,
        pending_proposals=pending_proposals,
        run_session_id=run_report.session_id,
        scenario_session_id=drafted.session_id,
    )


def format_agent_demo_report(result: AgentDemoResult) -> str:
    lines: list[str] = []
    w = lines.append

    w("=" * 70)
    w("FR Y-14 AGENT DEMO - Phases 9-11 (AG-1..AG-5, policy-enforced, traced)")
    w("=" * 70)
    w("")
    w(f"Database: {result.db_path}")
    w("")
    w("-- AG-1 Pipeline Operations " + "-" * 41)
    rr = result.run_report
    w(f"  pipeline_run_id      : {rr.pipeline_run_id}")
    w(
        f"  total / governed / quarantined : {rr.total_count} / "
        f"{rr.governed_count} / {rr.quarantined_count}"
    )
    w(f"  DQ pass rate         : {rr.dq_pass_percentage:.1f}%")
    w(f"  publish outcome      : {rr.publish_outcome} ({rr.publish_reason})")
    w(f"  triage handoff       : {rr.triage_handoff_recommended}")
    w("")
    w("-- AG-2 Data Quality Triage " + "-" * 41)
    w(f"  proposals created    : {len(result.quarantine_proposals)}")
    for p in result.quarantine_proposals:
        w(f"    {p.proposal_type} -> {p.payload.get('reason_code')}")
    w(f"  approved             : {len(result.approved_proposals)}")
    w(f"  records reprocessed  : {result.reprocessed_count}")
    w("")
    w("-- AG-4 Narrative (run) " + "-" * 45)
    w(f"  grounding_status     : {result.run_narrative.grounding_status}")
    w(f"  released             : {result.run_narrative_released}")
    w(f"  text                 : {result.run_narrative.rendered_text}")
    w("")
    w("-- AG-3 Stress Scenario " + "-" * 45)
    w(f"  summary              : {result.scenario_plain_language_summary}")
    w(f"  scenario_run_id      : {result.scenario_result.scenario_run_id}")
    w(f"  interpretation       : {result.scenario_interpretation}")
    w("")
    w("-- AG-4 Narrative (scenario) " + "-" * 40)
    w(f"  grounding_status     : {result.scenario_narrative.grounding_status}")
    w(f"  text                 : {result.scenario_narrative.rendered_text}")
    w("")
    w("-- AG-5 Data Product Concierge " + "-" * 37)
    w(f"  generated query      : {result.concierge_generated_query}")
    w(f"  rows returned        : {result.concierge_answer_row_count}")
    w("")
    w("-- Approval Queue (pending) " + "-" * 41)
    if result.pending_proposals:
        for p in result.pending_proposals:
            w(f"  {p.proposal_type} requested_by={p.requested_by} status={p.status}")
    else:
        w("  (empty)")
    w("")
    w("-- Scenario Comparison (baseline vs. stressed, first 5 rows) " + "-" * 7)
    for row in result.scenario_result.comparison_rows[:5]:
        w(
            f"  Q{row.quarter} {row.portfolio_segment:<16} grade={row.credit_rating_grade:<2} "
            f"dEAD={row.delta_ead:>14,.2f} dEL={row.delta_el:>12,.2f} dRWA={row.delta_rwa:>14,.2f}"
        )
    w("")
    w("=" * 70)
    w(
        "Note: the LLM calls above are a ScriptedLlmClient (fixed, labeled "
        "illustrative responses) — no model credentials are wired into this "
        "repo. Every number is still produced by the real deterministic "
        "engines; nothing here is hardcoded for display."
    )
    return "\n".join(lines)
