"""Stress run output models: `StressedLoanMetrics` (per loan, per quarter)
and `ScenarioComparisonRow` (baseline vs. stressed, aggregated by quarter x
segment x grade) plus the overall `ScenarioRunResult`. See
02-design-document.md §2.10 and schemas/012_scenario_runs.sql.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class StressedLoanMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_run_id: str
    loan_id: str
    quarter: int
    pd_stressed: Decimal
    lgd_stressed: Decimal
    ccf_stressed: Decimal
    ead_stressed: Decimal
    el_stressed: Decimal
    rwa_stressed: Decimal


class ScenarioComparisonRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_run_id: str
    quarter: int
    portfolio_segment: str
    credit_rating_grade: int
    ead_base: Decimal
    ead_stressed: Decimal
    el_base: Decimal
    el_stressed: Decimal
    rwa_base: Decimal
    rwa_stressed: Decimal
    loan_count: int

    @property
    def delta_ead(self) -> Decimal:
        return self.ead_stressed - self.ead_base

    @property
    def delta_el(self) -> Decimal:
        return self.el_stressed - self.el_base

    @property
    def delta_rwa(self) -> Decimal:
        return self.rwa_stressed - self.rwa_base


@dataclass
class ScenarioRunResult:
    scenario_run_id: str
    scenario_spec_id: str
    base_pipeline_run_id: str
    input_hash: str
    stress_engine_version: str
    translation_table_version: str
    regulatory_parameter_version: str
    classification: str
    stressed_loan_metrics: list[StressedLoanMetrics] = field(default_factory=list)
    comparison_rows: list[ScenarioComparisonRow] = field(default_factory=list)
    projected_loss_9q: Decimal = Decimal("0")
