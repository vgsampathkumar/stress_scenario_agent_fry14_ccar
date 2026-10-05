from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from fry14_engine.common.enums import MaturityBucket
from fry14_engine.pii.governed_models import GovernedLoanRecord
from fry14_engine.reference_data.models import RegulatoryParameterSet
from fry14_engine.risk_engine.engine import CALC_ENGINE_VERSION, RiskMetricEngine
from fry14_engine.risk_engine.models import CalculationException, LoanRiskMetrics


@pytest.fixture
def parameter_set() -> RegulatoryParameterSet:
    return RegulatoryParameterSet(
        version="1.0.0",
        effective_date=date(2026, 1, 1),
        ccf_by_key={("CRE", "STANDARD"): Decimal("0.5"), ("C&I", "STANDARD"): Decimal("0.2")},
        risk_weight_by_asset_class={"CRE": Decimal("1.00"), "C&I": Decimal("1.00")},
    )


def _governed_record(**overrides) -> GovernedLoanRecord:
    base = dict(
        governed_id="g-1",
        loan_id="LN-1",
        borrower_key_hash="hash-1",
        borrower_name_hash="hash-2",
        borrower_address_hash="hash-3",
        counterparty_id="CP-1",
        asset_class="CRE",
        internal_credit_risk_grade=5,
        credit_score=700,
        outstanding_balance=Decimal("1000000"),
        unadvanced_commitment=Decimal("500000"),
        maturity_date=date(2027, 6, 30),
        probability_of_default=Decimal("0.02"),
        loss_given_default=Decimal("0.45"),
        portfolio_segment="MIDDLE_MARKET",
        pipeline_run_id="run-1",
        contract_version="1.0.0",
        ingestion_timestamp=datetime(2026, 1, 1),
    )
    base.update(overrides)
    return GovernedLoanRecord(**base)


def test_successful_calculation_matches_hand_computed_values(parameter_set):
    engine = RiskMetricEngine(parameter_set)
    record = _governed_record()

    result = engine.run([record], reporting_period="2026-01", pipeline_run_id="run-1")

    assert len(result.metrics) == 1
    assert result.exceptions == []
    metrics = result.metrics[0]
    # EAD = 1,000,000 + 500,000 * 0.5 = 1,250,000
    assert metrics.ead == Decimal("1250000.0")
    # EL = 0.02 * 0.45 * 1,250,000 = 11,250
    assert metrics.el == Decimal("11250.00000")
    # RWA = 1,250,000 * 1.00
    assert metrics.rwa == Decimal("1250000.000000")
    assert metrics.calc_engine_version == CALC_ENGINE_VERSION
    assert metrics.regulatory_parameter_version == "1.0.0"
    assert metrics.remaining_maturity_bucket == MaturityBucket.M_13_36


def test_missing_pd_routes_to_calc_exception(parameter_set):
    engine = RiskMetricEngine(parameter_set)
    record = _governed_record(probability_of_default=None)

    result = engine.run([record], reporting_period="2026-01", pipeline_run_id="run-1")

    assert result.metrics == []
    assert len(result.exceptions) == 1
    assert result.exceptions[0].reason_code == "CALC_MISSING_PD_LGD"


def test_missing_lgd_routes_to_calc_exception(parameter_set):
    engine = RiskMetricEngine(parameter_set)
    record = _governed_record(loss_given_default=None)

    result = engine.run([record], reporting_period="2026-01", pipeline_run_id="run-1")

    assert result.exceptions[0].reason_code == "CALC_MISSING_PD_LGD"


def test_missing_maturity_date_routes_to_calc_exception(parameter_set):
    engine = RiskMetricEngine(parameter_set)
    record = _governed_record(maturity_date=None)

    result = engine.run([record], reporting_period="2026-01", pipeline_run_id="run-1")

    assert result.exceptions[0].reason_code == "CALC_MISSING_MATURITY_DATE"


def test_unknown_asset_class_routes_to_calc_exception(parameter_set):
    engine = RiskMetricEngine(parameter_set)
    record = _governed_record(asset_class="RESIDENTIAL")

    result = engine.run([record], reporting_period="2026-01", pipeline_run_id="run-1")

    assert result.exceptions[0].reason_code == "UNKNOWN_ASSET_CLASS"


def test_missing_unadvanced_commitment_defaults_to_zero_not_an_exception(parameter_set):
    engine = RiskMetricEngine(parameter_set)
    record = _governed_record(unadvanced_commitment=None)

    result = engine.run([record], reporting_period="2026-01", pipeline_run_id="run-1")

    assert result.exceptions == []
    assert result.metrics[0].ead == record.outstanding_balance


def test_missing_portfolio_segment_defaults_to_unspecified_not_an_exception(parameter_set):
    engine = RiskMetricEngine(parameter_set)
    record = _governed_record(portfolio_segment=None)

    result = engine.run([record], reporting_period="2026-01", pipeline_run_id="run-1")

    assert result.exceptions == []
    assert result.metrics[0].portfolio_segment == "UNSPECIFIED"


def test_one_bad_record_does_not_block_others_in_the_same_batch(parameter_set):
    """Fail-forward, same principle as contract validation (requirement 2.2)."""
    engine = RiskMetricEngine(parameter_set)
    good = _governed_record(loan_id="LN-GOOD")
    bad = _governed_record(loan_id="LN-BAD", probability_of_default=None)

    result = engine.run([good, bad], reporting_period="2026-01", pipeline_run_id="run-1")

    assert len(result.metrics) == 1
    assert result.metrics[0].loan_id == "LN-GOOD"
    assert len(result.exceptions) == 1
    assert result.exceptions[0].loan_id == "LN-BAD"


def test_rwa_is_identical_across_boundary_credit_grades(parameter_set):
    """Grade is an output dimension only — it must never change RWA/EAD/EL."""
    engine = RiskMetricEngine(parameter_set)
    low_grade = _governed_record(loan_id="LN-1", internal_credit_risk_grade=1)
    high_grade = _governed_record(loan_id="LN-2", internal_credit_risk_grade=10)

    result = engine.run(
        [low_grade, high_grade], reporting_period="2026-01", pipeline_run_id="run-1"
    )

    m1, m2 = result.metrics
    assert m1.ead == m2.ead
    assert m1.el == m2.el
    assert m1.rwa == m2.rwa
    assert m1.credit_rating_grade == 1
    assert m2.credit_rating_grade == 10


def test_reproducibility_same_input_same_parameter_version_yields_identical_output(parameter_set):
    engine = RiskMetricEngine(parameter_set)
    record = _governed_record()

    first = engine.run([record], reporting_period="2026-01", pipeline_run_id="run-1")
    second = engine.run([record], reporting_period="2026-01", pipeline_run_id="run-1")

    assert first.metrics[0].model_dump() == second.metrics[0].model_dump()


def test_calculation_exception_model_fields():
    exc = CalculationException(
        exception_id="e-1",
        loan_id="LN-1",
        pipeline_run_id="run-1",
        reason_code="CALC_MISSING_PD_LGD",
        detail="pd missing",
    )
    assert exc.reason_code == "CALC_MISSING_PD_LGD"


def test_loan_risk_metrics_requires_maturity_bucket_enum_value():
    metrics = LoanRiskMetrics(
        loan_id="LN-1",
        reporting_period="2026-01",
        ead=Decimal("1"),
        el=Decimal("1"),
        rwa=Decimal("1"),
        asset_class="CRE",
        portfolio_segment="MIDDLE_MARKET",
        credit_rating_grade=5,
        remaining_maturity_bucket=MaturityBucket.M_0_12,
        calc_engine_version="1.0.0",
        regulatory_parameter_version="1.0.0",
        pipeline_run_id="run-1",
    )
    assert metrics.remaining_maturity_bucket == MaturityBucket.M_0_12
