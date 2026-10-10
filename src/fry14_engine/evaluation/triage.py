"""Triage evaluation set (requirements.md AG-GOV-4, design doc §3.21):
synthetic quarantine clusters with a seeded, known root-cause dimension
(source system or counterparty), scored by whether a translator's
root-cause attribution matches the seeded ground truth. Pass bar: ≥90%
correct root cause + source.

**Scope note:** same as `scenario_translation.py` — no real LLM is wired
into this repo, so `RuleBasedTriageTranslator` is an illustrative,
deliberately simple frequency-based heuristic (attribute the cluster's
largest reason-code x source-system concentration), not a model.
"""

from __future__ import annotations

from datetime import datetime

from fry14_engine.evaluation.models import EvalCase, EvalCaseResult, EvalSetResult
from fry14_engine.quarantine.models import QuarantineRecord
from fry14_engine.quarantine.summary import build_quarantine_summary

PASS_BAR = 0.90


class RuleBasedTriageTranslator:
    """Illustrative stand-in for a real LLM — see module docstring."""

    model_id = "rule-based-triage-translator-v1"
    prompt_template_version = "1.0.0"

    @staticmethod
    def attribute_root_cause(records: list[QuarantineRecord], reason_code: str) -> str | None:
        summary = build_quarantine_summary(records)
        clusters = [c for c in summary.clusters if c.reason_code == reason_code]
        if not clusters:
            return None
        dominant = max(clusters, key=lambda c: c.record_count)
        return dominant.source_system_of_record


def _quarantine_record(
    quarantine_id: str, reason_code: str, source_system: str, rejected_at: datetime
) -> QuarantineRecord:
    return QuarantineRecord(
        quarantine_id=quarantine_id,
        loan_id=f"LN-{quarantine_id}",
        pipeline_run_id="eval-run",
        contract_id="commercial_loan",
        contract_version="1.0.0",
        original_record={"source_system_of_record": source_system},
        exception_reason_codes=(reason_code,),
        rejected_at=rejected_at,
    )


def _clean_case(case_id: str, reason_code: str, source_system: str, count: int) -> EvalCase:
    day = datetime(2026, 6, 1)
    records = [
        _quarantine_record(f"{case_id}-{i}", reason_code, source_system, day) for i in range(count)
    ]
    return EvalCase(
        case_id=case_id,
        inputs={"records": records, "reason_code": reason_code},
        expected={"source_system": source_system},
    )


def _noisy_case(
    case_id: str,
    reason_code: str,
    dominant_source: str,
    dominant_count: int,
    noise_source: str,
    noise_count: int,
) -> EvalCase:
    day = datetime(2026, 6, 1)
    records = [
        _quarantine_record(f"{case_id}-d{i}", reason_code, dominant_source, day)
        for i in range(dominant_count)
    ] + [
        _quarantine_record(f"{case_id}-n{i}", reason_code, noise_source, day)
        for i in range(noise_count)
    ]
    return EvalCase(
        case_id=case_id,
        inputs={"records": records, "reason_code": reason_code},
        expected={"source_system": dominant_source},
    )


GOLDEN_TRIAGE_CASES: list[EvalCase] = [
    # -- Clean, 100%-concentrated clusters (10) --------------------------
    *[_clean_case(f"clean-{i:02d}", "MISSING_CREDIT_SCORE", f"SOURCE_{i}", 5) for i in range(1, 6)],
    *[_clean_case(f"clean-{i:02d}", "NEGATIVE_BALANCE", f"CP-{i}", 4) for i in range(6, 11)],
    # -- Noisy clusters: a clear but not unanimous majority (6) ----------
    _noisy_case("noisy-01", "MISSING_CREDIT_SCORE", "LEGACY_CORE", 8, "MODERN_CORE", 2),
    _noisy_case("noisy-02", "MISSING_CREDIT_SCORE", "LEGACY_CORE", 9, "MODERN_CORE", 1),
    _noisy_case("noisy-03", "NEGATIVE_BALANCE", "CP-100", 7, "CP-200", 3),
    _noisy_case("noisy-04", "NEGATIVE_BALANCE", "CP-100", 6, "CP-200", 4),
    _noisy_case("noisy-05", "MISSING_CREDIT_SCORE", "LEGACY_CORE", 20, "MODERN_CORE", 5),
    _noisy_case("noisy-06", "NEGATIVE_BALANCE", "CP-100", 12, "CP-200", 3),
    # -- Genuinely ambiguous: a near-even split (2) — documented as a -----
    # known limitation of a frequency-only heuristic, not a harness bug.
    _noisy_case("ambiguous-01", "MISSING_CREDIT_SCORE", "LEGACY_CORE", 5, "MODERN_CORE", 5),
    _noisy_case("ambiguous-02", "NEGATIVE_BALANCE", "CP-100", 5, "CP-200", 5),
]


def run_triage_eval(translator: RuleBasedTriageTranslator | None = None) -> EvalSetResult:
    translator = translator or RuleBasedTriageTranslator()
    result = EvalSetResult(name="triage", pass_bar=PASS_BAR)

    for case in GOLDEN_TRIAGE_CASES:
        attributed = translator.attribute_root_cause(
            case.inputs["records"], case.inputs["reason_code"]
        )
        passed = attributed == case.expected["source_system"]
        result.case_results.append(
            EvalCaseResult(case.case_id, passed, f"attributed={attributed!r}")
        )

    return result
