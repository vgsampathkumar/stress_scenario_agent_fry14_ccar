"""Phase 11 Agent UI (AG-UI-1..4): a Streamlit rendering of the same
data `fry14 agent-demo` prints as text (see `agent_demo.py`'s own
docstring for the scope note this inherits). Run with:

    streamlit run src/fry14_engine/ui/app.py

Nothing here is mocked except the LLM, exactly as in the CLI demo: a
"Run agent demo" click calls the real `run_agent_demo()`, which drives
AG-1..AG-5 through the real `McpToolServer` / `PolicyEnforcementPoint` /
`AgentRuntime` stack and a `ScriptedLlmClient` (fixed, labeled
illustrative LLM responses — no model credentials are wired into this
repo). The Approval Queue tab's approve/reject buttons call the real
`ApprovalQueueService` against the same DuckDB file, so decisions made
here are the governed decisions, not UI-only state.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from fry14_engine.agent_demo import DEFAULT_AGENT_DEMO_DB_PATH, AgentDemoResult, run_agent_demo
from fry14_engine.agent_trace.models import AgentTraceEvent, AgentTraceEventType
from fry14_engine.approval_queue.models import AgentProposal
from fry14_engine.approval_queue.service import (
    ApprovalQueueService,
    DecisionReasonRequiredError,
    FourEyesViolationError,
    ProposalNotPendingError,
)
from fry14_engine.common.enums import Permission, RoleName
from fry14_engine.db import get_connection
from fry14_engine.rbac.matrix import ROLE_PERMISSION_MATRIX
from fry14_engine.rbac.service import PermissionDeniedError

st.set_page_config(page_title="FR Y-14 Agent Workspace", layout="wide")


def _roles_with(permission: Permission) -> list[RoleName]:
    return [role for role, perms in ROLE_PERMISSION_MATRIX.items() if permission in perms]


def _read_all_trace_events(db_path) -> list[AgentTraceEvent]:
    connection = get_connection(db_path)
    try:
        columns = [
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
            "event_timestamp",
        ]
        rows = connection.execute(
            f"SELECT {', '.join(columns)} FROM agent_governance.agent_trace_event "
            "ORDER BY session_id, event_timestamp"
        ).fetchall()
        events = []
        for row in rows:
            data = dict(zip(columns, row, strict=True))
            data["event_type"] = AgentTraceEventType(data["event_type"])
            events.append(AgentTraceEvent(**data))
        return events
    finally:
        connection.close()


def _read_pending_proposals(db_path) -> list[AgentProposal]:
    connection = get_connection(db_path)
    try:
        return ApprovalQueueService(connection).read_pending()
    finally:
        connection.close()


def _grounding_badge(status: str) -> str:
    return "🟢 PASSED" if status == "PASSED" else "🔴 FAILED"


def _sidebar() -> AgentDemoResult | None:
    st.sidebar.title("FR Y-14 Agent Workspace")
    st.sidebar.caption(
        "Governed Agentic Data Product Orchestrator — AG-1..AG-5, policy-enforced, traced."
    )
    st.sidebar.info(
        "⚠️ Synthetic illustrative data only. LLM steps use a `ScriptedLlmClient` "
        "(fixed, labeled responses) — no model credentials are wired into this repo. "
        "Every number shown is produced by the real deterministic engines."
    )

    count = st.sidebar.number_input("Clean records", min_value=5, max_value=200, value=20)
    seed = st.sidebar.number_input("Random seed", min_value=0, max_value=10_000, value=7)
    db_path = st.sidebar.text_input("DuckDB path", value=str(DEFAULT_AGENT_DEMO_DB_PATH))

    if st.sidebar.button("▶ Run agent demo", type="primary", use_container_width=True):
        with st.spinner("Running AG-1 → AG-5 through the real tool server and runtime..."):
            st.session_state["demo_result"] = run_agent_demo(
                db_path=db_path, count=int(count), seed=int(seed)
            )
            st.session_state["demo_db_path"] = db_path
        st.rerun()

    if "demo_result" in st.session_state:
        st.sidebar.success(f"Last run DB: {st.session_state['demo_db_path']}")

    return st.session_state.get("demo_result")


def _render_overview(result: AgentDemoResult | None) -> None:
    st.header("Conversational Workspace Overview")
    st.caption("AG-UI-1: the agents' shared operational picture alongside the pipeline dashboard.")
    if result is None:
        st.warning("Click **Run agent demo** in the sidebar to populate this workspace.")
        return

    rr = result.run_report
    cols = st.columns(5)
    cols[0].metric("Total records", rr.total_count)
    cols[1].metric("Governed", rr.governed_count)
    cols[2].metric("Quarantined", rr.quarantined_count)
    cols[3].metric("DQ pass rate", f"{rr.dq_pass_percentage:.1f}%")
    cols[4].metric("Projected 9Q loss", f"{result.scenario_result.projected_loss_9q:,.0f}")

    st.divider()
    st.subheader("What each agent did")
    st.markdown(
        f"- **AG-1** ran pipeline `{rr.pipeline_run_id[:8]}…`, publish outcome "
        f"**{rr.publish_outcome}** ({rr.publish_reason}); triage handoff: "
        f"**{rr.triage_handoff_recommended}**.\n"
        f"- **AG-2** created {len(result.quarantine_proposals)} remediation proposal(s), "
        f"{len(result.approved_proposals)} approved, "
        f"{result.reprocessed_count} record(s) reprocessed.\n"
        f"- **AG-3** ran scenario `{result.scenario_result.scenario_run_id[:8]}…` "
        f"({result.scenario_result.classification}).\n"
        f"- **AG-4** drafted 2 narratives; run narrative released: "
        f"**{result.run_narrative_released}**.\n"
        f"- **AG-5** answered a concierge question, returning "
        f"{result.concierge_answer_row_count} row(s).\n"
        f"- **{len(result.pending_proposals)}** proposal(s) await approval — see the "
        f"Approval Queue tab."
    )


def _render_ag1(result: AgentDemoResult | None) -> None:
    st.header("AG-1 — Pipeline Operations")
    if result is None:
        st.info("Run the demo first.")
        return
    rr = result.run_report
    st.json(
        {
            "pipeline_run_id": rr.pipeline_run_id,
            "session_id": rr.session_id,
            "data_product_id": rr.data_product_id,
            "publish_outcome": rr.publish_outcome,
            "publish_reason": rr.publish_reason,
            "publish_proposal_id": rr.publish_proposal_id,
            "triage_handoff_recommended": rr.triage_handoff_recommended,
        },
        expanded=False,
    )
    cols = st.columns(3)
    cols[0].metric(
        "Total / Governed / Quarantined",
        f"{rr.total_count} / {rr.governed_count} / {rr.quarantined_count}",
    )
    cols[1].metric(
        "Metrics computed", rr.metrics_computed, help=f"{rr.calculation_exceptions} exceptions"
    )
    cols[2].metric("Aggregate rows", rr.aggregate_rows)
    st.progress(
        min(rr.dq_pass_percentage / 100, 1.0), text=f"DQ pass rate: {rr.dq_pass_percentage:.1f}%"
    )

    if rr.reason_code_counts:
        st.subheader("Quarantine reason codes")
        st.dataframe(
            pd.DataFrame(
                sorted(rr.reason_code_counts.items(), key=lambda kv: -kv[1]),
                columns=["reason_code", "count"],
            ),
            use_container_width=True,
            hide_index=True,
        )


def _render_ag2(result: AgentDemoResult | None) -> None:
    st.header("AG-2 — Data Quality Triage")
    if result is None:
        st.info("Run the demo first.")
        return
    st.metric("Records reprocessed after approval", result.reprocessed_count)
    if not result.quarantine_proposals:
        st.caption("No proposals were created on this run.")
        return
    rows = []
    for p in result.quarantine_proposals:
        approved = any(a.proposal_id == p.proposal_id for a in result.approved_proposals)
        rows.append(
            {
                "proposal_id": p.proposal_id[:8] + "…",
                "type": p.proposal_type,
                "reason_code": p.payload.get("reason_code"),
                "rationale": p.rationale,
                "status": "APPROVED" if approved else p.status,
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_ag3(result: AgentDemoResult | None) -> None:
    st.header("AG-3 — Stress Scenario")
    st.caption("AG-UI-4: baseline vs. stressed comparison by segment, grade, and quarter.")
    if result is None:
        st.info("Run the demo first.")
        return
    sr = result.scenario_result
    st.markdown(f"**Request:** {result.scenario_plain_language_summary}")
    st.markdown(f"**Interpretation:** {result.scenario_interpretation}")
    cols = st.columns(4)
    cols[0].metric("Classification", sr.classification)
    cols[1].metric("Projected 9Q loss", f"{sr.projected_loss_9q:,.2f}")
    cols[2].metric("Translation table", sr.translation_table_version)
    cols[3].metric("Comparison rows", len(sr.comparison_rows))

    if not sr.comparison_rows:
        return
    df = pd.DataFrame(
        [
            {
                "quarter": r.quarter,
                "segment": r.portfolio_segment,
                "grade": r.credit_rating_grade,
                "ead_base": float(r.ead_base),
                "ead_stressed": float(r.ead_stressed),
                "delta_ead": float(r.delta_ead),
                "el_base": float(r.el_base),
                "el_stressed": float(r.el_stressed),
                "delta_el": float(r.delta_el),
                "delta_rwa": float(r.delta_rwa),
                "loan_count": r.loan_count,
            }
            for r in sr.comparison_rows
        ]
    )

    segments = sorted(df["segment"].unique())
    picked = st.multiselect("Filter by segment", segments, default=segments)
    filtered = df[df["segment"].isin(picked)]

    st.subheader("EL delta by segment and quarter")
    el_by_q = filtered.groupby(["quarter", "segment"])["delta_el"].sum().unstack("segment")
    st.bar_chart(el_by_q)

    st.subheader("Comparison detail")
    st.dataframe(
        filtered.sort_values(["quarter", "segment", "grade"]),
        use_container_width=True,
        hide_index=True,
    )


def _render_ag4(result: AgentDemoResult | None) -> None:
    st.header("AG-4 — Executive Reporting")
    st.caption(
        "AG-4.2 numeric grounding: every figure must trace back to a tool output; "
        "a mismatch blocks release."
    )
    if result is None:
        st.info("Run the demo first.")
        return

    st.subheader("Run narrative")
    st.markdown(_grounding_badge(result.run_narrative.grounding_status))
    st.markdown(f"> {result.run_narrative.rendered_text}")
    st.caption(f"Released: {result.run_narrative_released}")

    st.divider()
    st.subheader("Scenario narrative")
    st.markdown(_grounding_badge(result.scenario_narrative.grounding_status))
    st.markdown(f"> {result.scenario_narrative.rendered_text}")
    st.caption(
        f"Approval status: {result.scenario_narrative.approval_status} (pending release approval)"
    )


def _render_ag5(result: AgentDemoResult | None) -> None:
    st.header("AG-5 — Data Product Concierge")
    st.caption("AG-5.3: the generated query is shown alongside the answer for transparency.")
    if result is None:
        st.info("Run the demo first.")
        return
    st.markdown("**Question:** _What was total RWA last quarter?_")
    st.code(result.concierge_generated_query or "(refused)", language="sql")
    st.metric("Rows returned", result.concierge_answer_row_count)


def _render_approval_queue(db_path: str) -> None:
    st.header("Approval Queue")
    st.caption(
        "AG-UI-3: pending proposals with rationale and evidence; four-eyes and the "
        "approver's own RBAC permission are enforced by the real `ApprovalQueueService` "
        "— this is not UI-only state."
    )
    pending = _read_pending_proposals(db_path)
    if not pending:
        st.success("No pending proposals.")
        return

    for proposal in pending:
        with st.expander(
            f"{proposal.proposal_type} — requested by {proposal.requested_by} "
            f"(`{proposal.proposal_id[:8]}…`)",
            expanded=True,
        ):
            st.markdown(f"**Rationale:** {proposal.rationale or '—'}")
            if proposal.evidence:
                st.markdown("**Evidence:**")
                for e in proposal.evidence:
                    st.markdown(f"- {e}")
            st.json(proposal.payload, expanded=False)

            eligible_roles = _roles_with(proposal.required_permission)
            st.caption(f"Required permission: `{proposal.required_permission}`")

            with st.form(key=f"decide_{proposal.proposal_id}"):
                c1, c2, c3 = st.columns(3)
                approver_id = c1.text_input(
                    "Approver user id", value="approver.user", key=f"user_{proposal.proposal_id}"
                )
                approver_role = c2.selectbox(
                    "Approver role",
                    options=eligible_roles,
                    key=f"role_{proposal.proposal_id}",
                )
                decision = c3.radio(
                    "Decision", ["Approve", "Reject"], key=f"dec_{proposal.proposal_id}"
                )
                reason = st.text_area(
                    "Reason (required to reject)", key=f"reason_{proposal.proposal_id}"
                )
                submitted = st.form_submit_button("Submit decision")

            if submitted:
                connection = get_connection(db_path)
                try:
                    service = ApprovalQueueService(connection)
                    if decision == "Approve":
                        service.approve(proposal.proposal_id, approver_id, approver_role)
                    else:
                        service.reject(proposal.proposal_id, approver_id, approver_role, reason)
                    st.success(f"Proposal {proposal.proposal_id[:8]}… {decision.lower()}d.")
                    st.rerun()
                except FourEyesViolationError:
                    st.error("Four-eyes violation: the approver cannot be the requester.")
                except PermissionDeniedError as exc:
                    st.error(f"Permission denied: {exc}")
                except DecisionReasonRequiredError:
                    st.error("A reason is required to reject a proposal.")
                except ProposalNotPendingError:
                    st.error("This proposal is no longer pending (already decided elsewhere).")
                finally:
                    connection.close()


def _render_trace(db_path: str) -> None:
    st.header("Agent Trace")
    st.caption(
        "AG-UI-2: every plan, tool call, tool result, policy decision, proposal, "
        "approval, grounding check, and response — grouped by agent session."
    )
    events = _read_all_trace_events(db_path)
    if not events:
        st.info("No trace events yet. Run the demo first.")
        return

    by_session: dict[str, list[AgentTraceEvent]] = {}
    for event in events:
        by_session.setdefault(event.session_id, []).append(event)

    for session_id, session_events in by_session.items():
        agent_id = session_events[0].agent_id
        with st.expander(
            f"{agent_id} — session `{session_id[:8]}…` ({len(session_events)} events)"
        ):
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "timestamp": e.event_timestamp,
                            "event_type": e.event_type,
                            "tool_name": e.tool_name,
                            "payload_ref": e.payload_ref,
                            "latency_ms": e.latency_ms,
                        }
                        for e in session_events
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )


def main() -> None:
    result = _sidebar()
    db_path = st.session_state.get("demo_db_path", str(DEFAULT_AGENT_DEMO_DB_PATH))

    tabs = st.tabs(
        [
            "Overview",
            "AG-1 Pipeline Ops",
            "AG-2 DQ Triage",
            "AG-3 Stress Scenario",
            "AG-4 Exec Reporting",
            "AG-5 Concierge",
            "Approval Queue",
            "Agent Trace",
        ]
    )
    with tabs[0]:
        _render_overview(result)
    with tabs[1]:
        _render_ag1(result)
    with tabs[2]:
        _render_ag2(result)
    with tabs[3]:
        _render_ag3(result)
    with tabs[4]:
        _render_ag4(result)
    with tabs[5]:
        _render_ag5(result)
    with tabs[6]:
        _render_approval_queue(db_path)
    with tabs[7]:
        _render_trace(db_path)


if __name__ == "__main__":
    # Guarded, not a bare top-level call: both `streamlit run` and
    # `AppTest.from_file()` exec this script with `__name__ == "__main__"`,
    # so this still runs under either — but a plain `import
    # fry14_engine.ui.app` (e.g. to reuse a helper in a test) no longer
    # re-executes the whole app as a side effect, which was corrupting
    # Streamlit's global script-run state for any `AppTest` run
    # afterwards in the same process.
    main()
