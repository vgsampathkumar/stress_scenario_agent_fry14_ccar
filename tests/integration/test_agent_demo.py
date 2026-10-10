"""Agent demo (the "Agent UI" deliverable's CLI form, Phase 11) end-to-end
test — all five agents run back to back with no mocking except the LLM
itself. See agent_demo.py's own docstring.
"""

from __future__ import annotations

from pathlib import Path

from fry14_engine.agent_demo import run_agent_demo
from fry14_engine.approval_queue.models import ProposalStatus
from fry14_engine.grounding.models import GroundingStatus, NarrativeApprovalStatus


def test_run_agent_demo_end_to_end(tmp_db_path: Path):
    result = run_agent_demo(db_path=tmp_db_path, count=20, seed=7)

    assert result.run_report.quarantined_count > 0
    assert result.run_report.triage_handoff_recommended is True

    assert len(result.quarantine_proposals) == 1
    assert len(result.approved_proposals) == 1
    assert all(p.status == ProposalStatus.APPROVED for p in result.approved_proposals)
    assert result.reprocessed_count == result.run_report.quarantined_count

    assert result.run_narrative.grounding_status == GroundingStatus.PASSED
    assert result.run_narrative_released is True

    assert result.scenario_result.stressed_loan_metrics
    assert "RWA moved through" in result.scenario_interpretation
    assert result.scenario_narrative.grounding_status == GroundingStatus.PASSED
    assert result.scenario_narrative.approval_status == NarrativeApprovalStatus.DRAFT

    assert result.concierge_answer_row_count > 0
    assert "query_schedule" in result.concierge_generated_query

    # The publish proposal (DQ breach) and the scenario narrative's
    # release proposal are both still pending — only the run narrative
    # was released in the demo script.
    pending_types = {p.proposal_type for p in result.pending_proposals}
    assert "PUBLISH_OVERRIDE" in pending_types
    assert "NARRATIVE_RELEASE" in pending_types
