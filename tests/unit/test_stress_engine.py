"""Stress Engine (C28) tests built from hand-constructed, in-memory
reference data — no database involved, matching `RiskMetricEngine`'s own
test style. Covers requirement AG-3.5 ("a PD shock must change EL but not
RWA; a drawdown shock must change EAD, EL, and RWA") and replay
determinism via `input_hash`. See 02-design-document.md §3.18.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fry14_engine.pii.governed_models import GovernedLoanRecord
from fry14_engine.reference_data.models import RegulatoryParameterSet
from fry14_engine.risk_engine.models import LoanRiskMetrics
from fry14_engine.scenario.engine import StressEngine
from fry14_engine.scenario.input_hash import compute_input_hash
from fry14_engine.scenario.models import (
    GradePDGrid,
    MacroVariable,
    ScenarioName,
    ScenarioTranslationTable,
    ShockTransform,
    SupervisoryScenarioSet,
    TranslationTarget,
)
from fry14_engine.scenario.spec_models import (
    GradeMigration,
    PortfolioScope,
    ScenarioClassification,
    ScenarioSpec,
    ScenarioSpecStatus,
)

_PARAMETER_VERSION = "1.0.0"
_TRANSLATION_VERSION = "1.0.0"
_BASE_PIPELINE_RUN_ID = "pipeline-run-baseline-001"

_PARAMETER_SET = RegulatoryParameterSet(
    version=_PARAMETER_VERSION,
    effective_date=datetime(2026, 1, 1).date(),
    ccf_by_key={("CRE", "STANDARD"): Decimal("0.5")},
    risk_weight_by_asset_class={"CRE": Decimal("1.0")},
)

# A controlled unemployment path: zero jump-off-relative change at quarter
# 1, a +2.0pp change at quarter 2 — lets a test isolate "no shock yet" from
# "shock applied" within a single, two-quarter horizon.
_SUPERVISORY_SCENARIO = SupervisoryScenarioSet(
    scenario_version="TEST-SCENARIO",
    values={
        (ScenarioName.SEVERELY_ADVERSE, 0, MacroVariable.UNEMPLOYMENT_RATE): Decimal("4.0"),
        (ScenarioName.SEVERELY_ADVERSE, 1, MacroVariable.UNEMPLOYMENT_RATE): Decimal("4.0"),
        (ScenarioName.SEVERELY_ADVERSE, 2, MacroVariable.UNEMPLOYMENT_RATE): Decimal("6.0"),
    },
)


def _loan() -> GovernedLoanRecord:
    return GovernedLoanRecord(
        governed_id="governed-1",
        loan_id="loan-1",
        borrower_key_hash=None,
        borrower_name_hash=None,
        borrower_address_hash=None,
        counterparty_id=None,
        asset_class="CRE",
        internal_credit_risk_grade=5,
        credit_score=680,
        outstanding_balance=Decimal("1000000"),
        unadvanced_commitment=Decimal("500000"),
        maturity_date=None,
        probability_of_default=Decimal("0.02"),
        loss_given_default=Decimal("0.45"),
        portfolio_segment="MIDDLE_MARKET",
        pipeline_run_id=_BASE_PIPELINE_RUN_ID,
        contract_version="1.0.0",
        ingestion_timestamp=datetime(2026, 1, 15, 12, 0, 0),
    )


def _baseline_metrics(loan: GovernedLoanRecord) -> dict[str, LoanRiskMetrics]:
    ead = loan.outstanding_balance + loan.unadvanced_commitment * Decimal("0.5")
    el = loan.probability_of_default * loan.loss_given_default * ead
    rwa = ead * Decimal("1.0")
    return {
        loan.loan_id: LoanRiskMetrics(
            loan_id=loan.loan_id,
            reporting_period="2026-06",
            ead=ead,
            el=el,
            rwa=rwa,
            asset_class=loan.asset_class,
            portfolio_segment=loan.portfolio_segment,
            credit_rating_grade=loan.internal_credit_risk_grade,
            remaining_maturity_bucket="37-60M",
            calc_engine_version="1.0.0",
            regulatory_parameter_version=_PARAMETER_VERSION,
            pipeline_run_id=_BASE_PIPELINE_RUN_ID,
        )
    }


def _spec(horizon_quarters: int) -> ScenarioSpec:
    return ScenarioSpec(
        scenario_spec_id="spec-1",
        base_scenario=ScenarioName.SEVERELY_ADVERSE,
        supervisory_scenario_version="TEST-SCENARIO",
        portfolio_scope=PortfolioScope(reporting_period="2026-06"),
        horizon_quarters=horizon_quarters,
        translation_table_version=_TRANSLATION_VERSION,
        regulatory_parameter_version=_PARAMETER_VERSION,
        classification=ScenarioClassification.SUPERVISORY,
        status=ScenarioSpecStatus.DRAFT,
        requested_by="risk.analyst@example.com",
    )


def _pd_only_translation_table() -> ScenarioTranslationTable:
    key = ("MIDDLE_MARKET", "CRE", TranslationTarget.PD, MacroVariable.UNEMPLOYMENT_RATE)
    return ScenarioTranslationTable(
        version=_TRANSLATION_VERSION,
        effective_date=datetime(2026, 1, 1).date(),
        status="APPROVED",
        multiplier_floor=Decimal("0.5"),
        multiplier_cap=Decimal("5.0"),
        betas={key: Decimal("0.3")},
        transforms={key: ShockTransform.LEVEL_CHANGE},
        grade_sensitivity={5: Decimal("1.0")},
    )


def _drawdown_only_translation_table() -> ScenarioTranslationTable:
    key = ("MIDDLE_MARKET", "CRE", TranslationTarget.DRAWDOWN, MacroVariable.UNEMPLOYMENT_RATE)
    return ScenarioTranslationTable(
        version=_TRANSLATION_VERSION,
        effective_date=datetime(2026, 1, 1).date(),
        status="APPROVED",
        multiplier_floor=Decimal("0.5"),
        multiplier_cap=Decimal("5.0"),
        betas={key: Decimal("0.05")},
        transforms={key: ShockTransform.LEVEL_CHANGE},
        grade_sensitivity={5: Decimal("1.0")},
    )


def test_pd_only_shock_changes_el_but_not_rwa():
    loan = _loan()
    engine = StressEngine(_pd_only_translation_table(), _PARAMETER_SET, _SUPERVISORY_SCENARIO)
    result = engine.run(
        _spec(horizon_quarters=2), [loan], _baseline_metrics(loan), _BASE_PIPELINE_RUN_ID
    )

    by_quarter = {m.quarter: m for m in result.stressed_loan_metrics}
    assert by_quarter[1].pd_stressed != by_quarter[2].pd_stressed  # PD shock is active
    assert by_quarter[1].el_stressed != by_quarter[2].el_stressed  # EL moves with PD
    # No drawdown driver in this table: EAD (and therefore RWA, which has
    # no PD term at all) must be identical across quarters.
    assert by_quarter[1].ead_stressed == by_quarter[2].ead_stressed
    assert by_quarter[1].rwa_stressed == by_quarter[2].rwa_stressed


def test_drawdown_only_shock_changes_ead_el_and_rwa():
    loan = _loan()
    engine = StressEngine(_drawdown_only_translation_table(), _PARAMETER_SET, _SUPERVISORY_SCENARIO)
    result = engine.run(
        _spec(horizon_quarters=2), [loan], _baseline_metrics(loan), _BASE_PIPELINE_RUN_ID
    )

    by_quarter = {m.quarter: m for m in result.stressed_loan_metrics}
    # No PD/LGD driver in this table: PD and LGD must stay fixed.
    assert by_quarter[1].pd_stressed == by_quarter[2].pd_stressed
    assert by_quarter[1].lgd_stressed == by_quarter[2].lgd_stressed
    # Quarter 1 has zero jump-off-relative unemployment change (no shock
    # yet); quarter 2 has +2.0pp — EAD/EL/RWA must all move together.
    assert by_quarter[1].ccf_stressed < by_quarter[2].ccf_stressed
    assert by_quarter[1].ead_stressed < by_quarter[2].ead_stressed
    assert by_quarter[1].el_stressed < by_quarter[2].el_stressed
    assert by_quarter[1].rwa_stressed < by_quarter[2].rwa_stressed


def test_replay_with_same_input_hash_gives_identical_output():
    loan = _loan()
    baseline_metrics = _baseline_metrics(loan)
    translation_table = _pd_only_translation_table()

    spec_a = _spec(horizon_quarters=2).model_copy(update={"scenario_spec_id": "spec-a"})
    spec_b = _spec(horizon_quarters=2).model_copy(update={"scenario_spec_id": "spec-b"})
    assert spec_a.scenario_spec_id != spec_b.scenario_spec_id

    hash_a = compute_input_hash(spec_a, _BASE_PIPELINE_RUN_ID)
    hash_b = compute_input_hash(spec_b, _BASE_PIPELINE_RUN_ID)
    assert hash_a == hash_b  # identical content, different random IDs

    engine = StressEngine(translation_table, _PARAMETER_SET, _SUPERVISORY_SCENARIO)
    result_a = engine.run(
        spec_a, [loan], baseline_metrics, _BASE_PIPELINE_RUN_ID, scenario_run_id="replay-run"
    )
    result_b = engine.run(
        spec_b, [loan], baseline_metrics, _BASE_PIPELINE_RUN_ID, scenario_run_id="replay-run"
    )

    assert result_a.input_hash == result_b.input_hash == hash_a
    assert result_a.stressed_loan_metrics == result_b.stressed_loan_metrics
    assert result_a.comparison_rows == result_b.comparison_rows
    assert result_a.projected_loss_9q == result_b.projected_loss_9q


def test_loan_outside_portfolio_scope_is_excluded():
    loan = _loan()
    spec = _spec(horizon_quarters=1).model_copy(
        update={
            "portfolio_scope": PortfolioScope(reporting_period="2026-06", asset_classes=["C&I"])
        }
    )
    engine = StressEngine(_pd_only_translation_table(), _PARAMETER_SET, _SUPERVISORY_SCENARIO)
    result = engine.run(spec, [loan], _baseline_metrics(loan), _BASE_PIPELINE_RUN_ID)
    assert result.stressed_loan_metrics == []
    assert result.comparison_rows == []


def test_loan_without_baseline_metric_is_excluded():
    loan = _loan()
    engine = StressEngine(_pd_only_translation_table(), _PARAMETER_SET, _SUPERVISORY_SCENARIO)
    result = engine.run(_spec(horizon_quarters=1), [loan], {}, _BASE_PIPELINE_RUN_ID)
    assert result.stressed_loan_metrics == []


def test_loan_outside_portfolio_segment_scope_is_excluded():
    loan = _loan()
    spec = _spec(horizon_quarters=1).model_copy(
        update={
            "portfolio_scope": PortfolioScope(
                reporting_period="2026-06", portfolio_segments=["LARGE_CORPORATE"]
            )
        }
    )
    engine = StressEngine(_pd_only_translation_table(), _PARAMETER_SET, _SUPERVISORY_SCENARIO)
    result = engine.run(spec, [loan], _baseline_metrics(loan), _BASE_PIPELINE_RUN_ID)
    assert result.stressed_loan_metrics == []


def test_loan_outside_credit_grade_scope_is_excluded():
    loan = _loan()
    spec = _spec(horizon_quarters=1).model_copy(
        update={"portfolio_scope": PortfolioScope(reporting_period="2026-06", credit_grades=[9])}
    )
    engine = StressEngine(_pd_only_translation_table(), _PARAMETER_SET, _SUPERVISORY_SCENARIO)
    result = engine.run(spec, [loan], _baseline_metrics(loan), _BASE_PIPELINE_RUN_ID)
    assert result.stressed_loan_metrics == []


def test_grade_migration_applies_grid_pd_for_matching_segment():
    loan = _loan()  # grade 5, segment MIDDLE_MARKET
    grid = GradePDGrid(version="1.0.0", pd_by_grade={7: Decimal("0.03")})
    spec = _spec(horizon_quarters=1).model_copy(
        update={"grade_migration": GradeMigration(notches=2)}  # 5 + 2 = grade 7
    )
    engine = StressEngine(
        _pd_only_translation_table(),
        _PARAMETER_SET,
        _SUPERVISORY_SCENARIO,
        grade_pd_grid=grid,
    )
    result = engine.run(spec, [loan], _baseline_metrics(loan), _BASE_PIPELINE_RUN_ID)
    stressed = result.stressed_loan_metrics[0]
    # Effective PD should start from the grid's grade-7 PD (0.03), not the
    # loan's own PD (0.02) — confirmed by the quarter-1 (no shock yet) value.
    assert stressed.pd_stressed == Decimal("0.0300")


def test_grade_migration_skipped_for_non_matching_segment():
    loan = _loan()  # segment MIDDLE_MARKET
    grid = GradePDGrid(version="1.0.0", pd_by_grade={7: Decimal("0.03")})
    spec = _spec(horizon_quarters=1).model_copy(
        update={"grade_migration": GradeMigration(notches=2, segments=["SMALL_BUSINESS"])}
    )
    engine = StressEngine(
        _pd_only_translation_table(),
        _PARAMETER_SET,
        _SUPERVISORY_SCENARIO,
        grade_pd_grid=grid,
    )
    result = engine.run(spec, [loan], _baseline_metrics(loan), _BASE_PIPELINE_RUN_ID)
    stressed = result.stressed_loan_metrics[0]
    # Segment doesn't match the migration scope: falls back to the loan's
    # own PD (0.02), not the grid's grade-7 PD (0.03).
    assert stressed.pd_stressed == Decimal("0.0200")
