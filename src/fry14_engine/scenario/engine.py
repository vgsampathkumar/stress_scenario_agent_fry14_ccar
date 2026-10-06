"""Stress Engine (C28) orchestration: applies `stress_calculator`'s pure
formulas to every in-scope governed loan, for every projection quarter,
producing `StressedLoanMetrics` and the baseline-vs-stressed
`ScenarioComparisonRow` aggregates. Pure and DB-free — mirrors
`RiskMetricEngine` taking an already-loaded `RegulatoryParameterSet`. See
02-design-document.md §3.18.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from fry14_engine.common.ids import new_record_id
from fry14_engine.pii.governed_models import GovernedLoanRecord
from fry14_engine.reference_data.models import RegulatoryParameterSet
from fry14_engine.risk_engine.models import LoanRiskMetrics
from fry14_engine.scenario.input_hash import compute_input_hash
from fry14_engine.scenario.models import (
    GradePDGrid,
    ScenarioTranslationTable,
    SupervisoryScenarioSet,
    TranslationTarget,
)
from fry14_engine.scenario.run_models import (
    ScenarioComparisonRow,
    ScenarioRunResult,
    StressedLoanMetrics,
)
from fry14_engine.scenario.spec_models import AdhocShock, ScenarioSpec
from fry14_engine.scenario.stress_calculator import (
    compute_delta_x,
    compute_drawdown_uplift,
    compute_lgd_multiplier,
    compute_pd_multiplier,
    compute_stressed_ccf,
    compute_stressed_ead,
    compute_stressed_el,
    compute_stressed_lgd,
    compute_stressed_pd,
    compute_stressed_rwa,
)

STRESS_ENGINE_VERSION = "1.0.0"
DEFAULT_COMMITMENT_TYPE = "STANDARD"
_CENTS = Decimal("0.01")
_FOUR_PLACES = Decimal("0.0001")


def _round_to_cents(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _round_to_four_places(value: Decimal) -> Decimal:
    return value.quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class _GroupKey:
    quarter: int
    portfolio_segment: str
    credit_rating_grade: int


def _loan_in_scope(loan: GovernedLoanRecord, spec: ScenarioSpec) -> bool:
    scope = spec.portfolio_scope
    if (
        scope.portfolio_segments is not None
        and loan.portfolio_segment not in scope.portfolio_segments
    ):
        return False
    if scope.asset_classes is not None and loan.asset_class not in scope.asset_classes:
        return False
    if (
        scope.credit_grades is not None
        and loan.internal_credit_risk_grade not in scope.credit_grades
    ):
        return False
    return True


class StressEngine:
    def __init__(
        self,
        translation_table: ScenarioTranslationTable,
        parameter_set: RegulatoryParameterSet,
        supervisory_scenario: SupervisoryScenarioSet | None = None,
        grade_pd_grid: GradePDGrid | None = None,
    ) -> None:
        self._translation_table = translation_table
        self._parameter_set = parameter_set
        self._supervisory_scenario = supervisory_scenario
        self._grade_pd_grid = grade_pd_grid

    def run(
        self,
        spec: ScenarioSpec,
        governed_loans: list[GovernedLoanRecord],
        baseline_metrics_by_loan_id: dict[str, LoanRiskMetrics],
        base_pipeline_run_id: str,
        scenario_run_id: str | None = None,
    ) -> ScenarioRunResult:
        scenario_run_id = scenario_run_id or new_record_id()
        in_scope_loans = [
            loan
            for loan in governed_loans
            if _loan_in_scope(loan, spec) and loan.loan_id in baseline_metrics_by_loan_id
        ]

        stressed_rows: list[StressedLoanMetrics] = []
        groups: dict[_GroupKey, list[tuple[LoanRiskMetrics, StressedLoanMetrics]]] = defaultdict(
            list
        )

        for loan in in_scope_loans:
            baseline = baseline_metrics_by_loan_id[loan.loan_id]
            base_ccf = self._parameter_set.get_ccf(loan.asset_class, DEFAULT_COMMITMENT_TYPE)
            risk_weight = self._parameter_set.get_risk_weight(loan.asset_class)
            effective_pd = self._effective_pd(loan, spec)

            for quarter in range(1, spec.horizon_quarters + 1):
                stressed = self._stress_one_loan_one_quarter(
                    loan=loan,
                    quarter=quarter,
                    effective_pd=effective_pd,
                    base_ccf=base_ccf,
                    risk_weight=risk_weight,
                    scenario_run_id=scenario_run_id,
                    scenario_name=spec.base_scenario,
                    adhoc_shocks=spec.adhoc_shocks,
                )
                stressed_rows.append(stressed)
                key = _GroupKey(
                    quarter,
                    loan.portfolio_segment or "UNSPECIFIED",
                    loan.internal_credit_risk_grade,
                )
                groups[key].append((baseline, stressed))

        comparison_rows = [
            ScenarioComparisonRow(
                scenario_run_id=scenario_run_id,
                quarter=key.quarter,
                portfolio_segment=key.portfolio_segment,
                credit_rating_grade=key.credit_rating_grade,
                ead_base=sum((b.ead for b, _s in pairs), start=Decimal("0")),
                ead_stressed=sum((s.ead_stressed for _b, s in pairs), start=Decimal("0")),
                el_base=sum((b.el for b, _s in pairs), start=Decimal("0")),
                el_stressed=sum((s.el_stressed for _b, s in pairs), start=Decimal("0")),
                rwa_base=sum((b.rwa for b, _s in pairs), start=Decimal("0")),
                rwa_stressed=sum((s.rwa_stressed for _b, s in pairs), start=Decimal("0")),
                loan_count=len(pairs),
            )
            for key, pairs in groups.items()
        ]

        # Illustrative only — treats EL as an annualized rate applied
        # quarterly; see 02-design-document.md §3.18.
        total_el_stressed = sum((row.el_stressed for row in stressed_rows), start=Decimal("0"))
        projected_loss_9q = _round_to_cents(total_el_stressed / Decimal(4))

        return ScenarioRunResult(
            scenario_run_id=scenario_run_id,
            scenario_spec_id=spec.scenario_spec_id,
            base_pipeline_run_id=base_pipeline_run_id,
            input_hash=compute_input_hash(spec, base_pipeline_run_id),
            stress_engine_version=STRESS_ENGINE_VERSION,
            translation_table_version=self._translation_table.version,
            regulatory_parameter_version=spec.regulatory_parameter_version,
            classification=str(spec.classification),
            stressed_loan_metrics=stressed_rows,
            comparison_rows=comparison_rows,
            projected_loss_9q=projected_loss_9q,
        )

    def _effective_pd(self, loan: GovernedLoanRecord, spec: ScenarioSpec) -> Decimal:
        migration = spec.grade_migration
        if migration is None or self._grade_pd_grid is None:
            return loan.probability_of_default
        if migration.segments is not None and loan.portfolio_segment not in migration.segments:
            return loan.probability_of_default
        migrated_grade = max(1, min(10, loan.internal_credit_risk_grade + migration.notches))
        return self._grade_pd_grid.get_pd(migrated_grade)

    def _stress_one_loan_one_quarter(
        self,
        loan: GovernedLoanRecord,
        quarter: int,
        effective_pd: Decimal,
        base_ccf: Decimal,
        risk_weight: Decimal,
        scenario_run_id: str,
        scenario_name,
        adhoc_shocks: list[AdhocShock],
    ) -> StressedLoanMetrics:
        segment = loan.portfolio_segment or "UNSPECIFIED"
        supervisory_values = (
            self._supervisory_scenario.values if self._supervisory_scenario is not None else None
        )

        def sum_shock(target: TranslationTarget) -> Decimal:
            betas = self._translation_table.betas_for(segment, loan.asset_class, target)
            return sum(
                (
                    beta
                    * compute_delta_x(
                        variable,
                        quarter,
                        transform,
                        scenario_name,
                        supervisory_values,
                        adhoc_shocks,
                    )
                    for variable, (beta, transform) in betas.items()
                ),
                start=Decimal("0"),
            )

        s_pd = sum_shock(TranslationTarget.PD)
        s_lgd = sum_shock(TranslationTarget.LGD)
        s_drawdown = sum_shock(TranslationTarget.DRAWDOWN)

        grade_scaling = self._translation_table.grade_scaling(loan.internal_credit_risk_grade)
        pd_multiplier = compute_pd_multiplier(
            s_pd,
            grade_scaling,
            self._translation_table.multiplier_floor,
            self._translation_table.multiplier_cap,
        )
        lgd_multiplier = compute_lgd_multiplier(
            s_lgd, self._translation_table.multiplier_floor, self._translation_table.multiplier_cap
        )
        drawdown_uplift = compute_drawdown_uplift(s_drawdown, base_ccf)

        pd_stressed = compute_stressed_pd(effective_pd, pd_multiplier)
        lgd_stressed = compute_stressed_lgd(loan.loss_given_default, lgd_multiplier)
        ccf_stressed = compute_stressed_ccf(base_ccf, drawdown_uplift)
        ead_stressed = _round_to_cents(
            compute_stressed_ead(
                loan.outstanding_balance, loan.unadvanced_commitment or Decimal("0"), ccf_stressed
            )
        )
        el_stressed = _round_to_cents(compute_stressed_el(pd_stressed, lgd_stressed, ead_stressed))
        rwa_stressed = _round_to_cents(compute_stressed_rwa(ead_stressed, risk_weight))

        return StressedLoanMetrics(
            scenario_run_id=scenario_run_id,
            loan_id=loan.loan_id,
            quarter=quarter,
            pd_stressed=_round_to_four_places(pd_stressed),
            lgd_stressed=_round_to_four_places(lgd_stressed),
            ccf_stressed=_round_to_four_places(ccf_stressed),
            ead_stressed=ead_stressed,
            el_stressed=el_stressed,
            rwa_stressed=rwa_stressed,
        )
