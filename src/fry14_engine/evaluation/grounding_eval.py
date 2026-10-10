"""Grounding evaluation set (requirements.md AG-GOV-4, design doc §3.21):
narrative fixtures from representative runs, scored against the real
`GroundingChecker` — no illustrative stand-in needed here, since the
checker itself is deterministic, already-production code (not an LLM).
Pass bar: 100% bound figures; 0 unbound numbers released.
"""

from __future__ import annotations

from fry14_engine.evaluation.models import EvalCase, EvalCaseResult, EvalSetResult
from fry14_engine.grounding.checker import GroundingChecker
from fry14_engine.grounding.models import GroundingStatus

PASS_BAR = 1.0

_RESOLVABLE = {
    "run:abc123.governed_count": "920",
    "run:abc123.dq_pass_percentage": "92.00",
    "scenario:def456.projected_loss_9q": "1,250,340.10",
    "scenario:def456.segment.CRE.delta_el": "875,200.00",
}


def _resolver(token: str) -> str | None:
    return _RESOLVABLE.get(token)


GOLDEN_GROUNDING_CASES: list[EvalCase] = [
    EvalCase(
        "passing-run-narrative",
        {
            "template_text": (
                "We governed {{run:abc123.governed_count}} loans "
                "({{run:abc123.dq_pass_percentage}}% DQ pass rate) in Q2 2026."
            )
        },
        {"expected_status": "PASSED", "should_release": True},
    ),
    EvalCase(
        "passing-scenario-narrative",
        {
            "template_text": (
                "Severely Adverse raises CRE expected loss by "
                "{{scenario:def456.segment.CRE.delta_el}}; nine-quarter projected "
                "loss is {{scenario:def456.projected_loss_9q}}."
            )
        },
        {"expected_status": "PASSED", "should_release": True},
    ),
    EvalCase(
        "injected-free-number",
        {"template_text": "We governed 920 loans (92% DQ pass rate) in Q2 2026."},
        {"expected_status": "FAILED", "should_release": False},
    ),
    EvalCase(
        "mixed-bound-and-free-number",
        {
            "template_text": (
                "DQ rose to {{run:abc123.dq_pass_percentage}}%, roughly 4 points "
                "better than plan."
            )
        },
        {"expected_status": "FAILED", "should_release": False},
    ),
    EvalCase(
        "unresolvable-binding",
        {"template_text": "We governed {{run:nonexistent.governed_count}} loans."},
        {"expected_status": "FAILED", "should_release": False},
    ),
    EvalCase(
        "qualitative_only",
        {"template_text": "Data quality improved materially versus the prior run."},
        {"expected_status": "PASSED", "should_release": True},
    ),
    EvalCase(
        "allowlisted_terms_only",
        {"template_text": "Filed under FR Y-14 / CCAR for the 2026-06 period, comparing Q1 to Q3."},
        {"expected_status": "PASSED", "should_release": True},
    ),
]


def run_grounding_eval(checker: GroundingChecker | None = None) -> EvalSetResult:
    checker = checker or GroundingChecker()
    result = EvalSetResult(name="grounding", pass_bar=PASS_BAR)

    for case in GOLDEN_GROUNDING_CASES:
        grounding_result = checker.check(case.inputs["template_text"], _resolver)
        passed = str(grounding_result.status) == case.expected["expected_status"]
        released = grounding_result.status == GroundingStatus.PASSED
        if released != case.expected["should_release"]:
            passed = False
        result.case_results.append(
            EvalCaseResult(case.case_id, passed, f"status={grounding_result.status}")
        )

    return result
