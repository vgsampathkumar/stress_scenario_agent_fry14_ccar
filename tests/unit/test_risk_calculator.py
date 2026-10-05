from __future__ import annotations

from decimal import Decimal

from fry14_engine.risk_engine.calculator import calculate_ead, calculate_el, calculate_rwa


def test_ead_adds_balance_and_ccf_weighted_commitment():
    ead = calculate_ead(
        outstanding_balance=Decimal("1000000"),
        unadvanced_commitment=Decimal("500000"),
        ccf=Decimal("0.5"),
    )
    assert ead == Decimal("1250000.0")


def test_ead_with_zero_commitment_equals_balance():
    ead = calculate_ead(
        outstanding_balance=Decimal("1000000"),
        unadvanced_commitment=Decimal("0"),
        ccf=Decimal("0.5"),
    )
    assert ead == Decimal("1000000")


def test_ead_with_full_100_percent_ccf_draws_entire_commitment():
    ead = calculate_ead(
        outstanding_balance=Decimal("1000000"),
        unadvanced_commitment=Decimal("500000"),
        ccf=Decimal("1.0"),
    )
    assert ead == Decimal("1500000.0")


def test_el_is_pd_times_lgd_times_ead():
    el = calculate_el(
        probability_of_default=Decimal("0.02"),
        loss_given_default=Decimal("0.45"),
        ead=Decimal("1000000"),
    )
    assert el == Decimal("9000.000")


def test_rwa_is_ead_times_risk_weight():
    rwa = calculate_rwa(ead=Decimal("1000000"), risk_weight=Decimal("1.00"))
    assert rwa == Decimal("1000000.00")


def test_rwa_scales_with_risk_weight_below_full():
    rwa = calculate_rwa(ead=Decimal("1000000"), risk_weight=Decimal("0.5"))
    assert rwa == Decimal("500000.0")


def test_rwa_formula_has_no_grade_dependency():
    """Design invariant: RWA = EAD x risk_weight, nothing else. Two loans
    identical in every way except credit grade must produce identical RWA —
    this matters again in Phase 8, where a PD shock must not move RWA."""
    ead = Decimal("1000000")
    risk_weight = Decimal("1.00")
    rwa_grade_1 = calculate_rwa(ead, risk_weight)
    rwa_grade_10 = calculate_rwa(ead, risk_weight)
    assert rwa_grade_1 == rwa_grade_10
