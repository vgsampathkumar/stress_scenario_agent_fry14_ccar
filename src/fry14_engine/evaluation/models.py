"""Evaluation Harness (C30) models: a golden `EvalCase`, the per-case
`EvalCaseResult`, and the aggregated `EvalSetResult` each evaluation set
(scenario translation, triage, grounding, guardrails, prompt injection)
returns. See 02-design-document.md §3.21 and requirements.md AG-GOV-4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvalCaseResult:
    case_id: str
    passed: bool
    detail: str = ""


@dataclass
class EvalSetResult:
    name: str
    pass_bar: float  # e.g. 0.95 for "≥95%"
    case_results: list[EvalCaseResult] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        return len(self.case_results)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.case_results if r.passed)

    @property
    def pass_rate(self) -> float:
        return self.pass_count / self.total_count if self.total_count else 1.0

    @property
    def meets_bar(self) -> bool:
        return self.pass_rate >= self.pass_bar

    @property
    def failures(self) -> list[EvalCaseResult]:
        return [r for r in self.case_results if not r.passed]


@dataclass(frozen=True)
class EvalCase:
    """A single golden-set fixture; `inputs`/`expected` shapes are defined
    per evaluation set (scenario translation, triage, ...), not shared."""

    case_id: str
    inputs: dict[str, Any]
    expected: dict[str, Any]
