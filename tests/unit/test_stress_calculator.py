"""Hand-calculated fixtures for the Stress Engine (C28) pure formulas. See
02-design-document.md §3.18 and requirement AG-3.5.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from fry14_engine.scenario.models import MacroVariable, ScenarioName, ShockTransform
from fry14_engine.scenario.spec_models import AdhocShock, AdhocShockType
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

_UNEMPLOYMENT_PATH = {
    (ScenarioName.SEVERELY_ADVERSE, 0, MacroVariable.UNEMPLOYMENT_RATE): Decimal("4.0"),
    (ScenarioName.SEVERELY_ADVERSE, 1, MacroVariable.UNEMPLOYMENT_RATE): Decimal("5.5"),
    (ScenarioName.SEVERELY_ADVERSE, 5, MacroVariable.UNEMPLOYMENT_RATE): Decimal("10.0"),
}
_CRE_PRICE_PATH = {
    (ScenarioName.SEVERELY_ADVERSE, 0, MacroVariable.CRE_PRICE_INDEX): Decimal("100.0"),
    (ScenarioName.SEVERELY_ADVERSE, 1, MacroVariable.CRE_PRICE_INDEX): Decimal("92.0"),
}


class TestComputeDeltaX:
    def test_level_change_is_jump_off_relative(self):
        delta = compute_delta_x(
            MacroVariable.UNEMPLOYMENT_RATE,
            1,
            ShockTransform.LEVEL_CHANGE,
            ScenarioName.SEVERELY_ADVERSE,
            _UNEMPLOYMENT_PATH,
            [],
        )
        assert delta == Decimal("1.5")  # 5.5 - 4.0

    def test_level_change_at_trough_quarter(self):
        delta = compute_delta_x(
            MacroVariable.UNEMPLOYMENT_RATE,
            5,
            ShockTransform.LEVEL_CHANGE,
            ScenarioName.SEVERELY_ADVERSE,
            _UNEMPLOYMENT_PATH,
            [],
        )
        assert delta == Decimal("6.0")  # 10.0 - 4.0

    def test_pct_change_transform(self):
        delta = compute_delta_x(
            MacroVariable.CRE_PRICE_INDEX,
            1,
            ShockTransform.PCT_CHANGE,
            ScenarioName.SEVERELY_ADVERSE,
            _CRE_PRICE_PATH,
            [],
        )
        assert delta == Decimal("-0.08")  # (92 - 100) / 100

    def test_no_supervisory_scenario_leaves_only_adhoc_contribution(self):
        shock = AdhocShock(
            variable=MacroVariable.UNEMPLOYMENT_RATE,
            shock_type=AdhocShockType.ADD_PCT_POINTS,
            magnitude=Decimal("2"),
            quarters=[1],
        )
        delta = compute_delta_x(
            MacroVariable.UNEMPLOYMENT_RATE,
            1,
            ShockTransform.LEVEL_CHANGE,
            None,
            None,
            [shock],
        )
        assert delta == Decimal("2")

    def test_adhoc_add_bps_converts_to_percentage_points(self):
        shock = AdhocShock(
            variable=MacroVariable.UNEMPLOYMENT_RATE,
            shock_type=AdhocShockType.ADD_BPS,
            magnitude=Decimal("100"),
            quarters=[1],
        )
        delta = compute_delta_x(
            MacroVariable.UNEMPLOYMENT_RATE,
            1,
            ShockTransform.LEVEL_CHANGE,
            ScenarioName.SEVERELY_ADVERSE,
            _UNEMPLOYMENT_PATH,
            [shock],
        )
        assert delta == Decimal("2.5")  # 1.5 supervisory + 1.0 from 100bps

    def test_adhoc_shock_wrong_quarter_does_not_contribute(self):
        shock = AdhocShock(
            variable=MacroVariable.UNEMPLOYMENT_RATE,
            shock_type=AdhocShockType.ADD_PCT_POINTS,
            magnitude=Decimal("2"),
            quarters=[2],
        )
        delta = compute_delta_x(
            MacroVariable.UNEMPLOYMENT_RATE,
            1,
            ShockTransform.LEVEL_CHANGE,
            ScenarioName.SEVERELY_ADVERSE,
            _UNEMPLOYMENT_PATH,
            [shock],
        )
        assert delta == Decimal("1.5")

    def test_pct_change_shock_against_level_change_transform_contributes_zero(self):
        shock = AdhocShock(
            variable=MacroVariable.UNEMPLOYMENT_RATE,
            shock_type=AdhocShockType.PCT_CHANGE,
            magnitude=Decimal("0.1"),
            quarters=[1],
        )
        delta = compute_delta_x(
            MacroVariable.UNEMPLOYMENT_RATE,
            1,
            ShockTransform.LEVEL_CHANGE,
            ScenarioName.SEVERELY_ADVERSE,
            _UNEMPLOYMENT_PATH,
            [shock],
        )
        assert delta == Decimal("1.5")  # only the supervisory contribution


class TestMultipliersAndUplift:
    def test_pd_multiplier_clamps_to_cap(self):
        multiplier = compute_pd_multiplier(
            Decimal("10"), Decimal("1"), Decimal("0.5"), Decimal("5.0")
        )
        assert multiplier == Decimal("5.0")

    def test_pd_multiplier_clamps_to_floor(self):
        multiplier = compute_pd_multiplier(
            Decimal("-10"), Decimal("1"), Decimal("0.5"), Decimal("5.0")
        )
        assert multiplier == Decimal("0.5")

    def test_pd_multiplier_within_bounds_is_unclamped(self):
        multiplier = compute_pd_multiplier(
            Decimal("1"), Decimal("0.5"), Decimal("0.5"), Decimal("5.0")
        )
        assert multiplier == Decimal("1.5")  # 1 + 0.5 * 1

    def test_lgd_multiplier_clamps_to_cap(self):
        multiplier = compute_lgd_multiplier(Decimal("10"), Decimal("0.5"), Decimal("5.0"))
        assert multiplier == Decimal("5.0")

    def test_drawdown_uplift_clamps_to_zero_floor(self):
        uplift = compute_drawdown_uplift(Decimal("-0.1"), Decimal("0.5"))
        assert uplift == Decimal("0")

    def test_drawdown_uplift_clamps_to_remaining_headroom(self):
        uplift = compute_drawdown_uplift(Decimal("10"), Decimal("0.5"))
        assert uplift == Decimal("0.5")  # 1 - base_ccf

    def test_drawdown_uplift_within_bounds_is_unclamped(self):
        uplift = compute_drawdown_uplift(Decimal("0.2"), Decimal("0.5"))
        assert uplift == Decimal("0.2")


class TestStressedMetrics:
    def test_stressed_pd_caps_at_one(self):
        assert compute_stressed_pd(Decimal("0.5"), Decimal("3")) == Decimal("1")

    def test_stressed_pd_uncapped(self):
        assert compute_stressed_pd(Decimal("0.02"), Decimal("2")) == Decimal("0.04")

    def test_stressed_lgd_caps_at_one(self):
        assert compute_stressed_lgd(Decimal("0.6"), Decimal("2")) == Decimal("1")

    def test_stressed_lgd_uncapped(self):
        assert compute_stressed_lgd(Decimal("0.3"), Decimal("2")) == Decimal("0.6")

    def test_stressed_ccf(self):
        assert compute_stressed_ccf(Decimal("0.5"), Decimal("0.2")) == Decimal("0.7")

    def test_stressed_ead(self):
        ead = compute_stressed_ead(Decimal("1000000"), Decimal("500000"), Decimal("0.7"))
        assert ead == Decimal("1350000")

    def test_stressed_el(self):
        el = compute_stressed_el(Decimal("0.04"), Decimal("0.6"), Decimal("1350000"))
        assert el == Decimal("32400")

    def test_stressed_rwa_depends_only_on_ead_and_risk_weight(self):
        # By construction `compute_stressed_rwa` has no PD parameter at
        # all — two wildly different stressed-PD scenarios that happen to
        # land on the same EAD must produce identical RWA (AG-3.5).
        pd_mild = compute_stressed_pd(Decimal("0.02"), Decimal("1.1"))
        pd_severe = compute_stressed_pd(Decimal("0.02"), Decimal("4.0"))
        assert pd_mild != pd_severe

        rwa_under_mild_pd = compute_stressed_rwa(Decimal("1350000"), Decimal("1.0"))
        rwa_under_severe_pd = compute_stressed_rwa(Decimal("1350000"), Decimal("1.0"))
        assert rwa_under_mild_pd == rwa_under_severe_pd == Decimal("1350000")


@pytest.mark.parametrize(
    ("shock_type", "transform", "expected"),
    [
        (AdhocShockType.ADD_BPS, ShockTransform.LEVEL_CHANGE, Decimal("1")),
        (AdhocShockType.ADD_PCT_POINTS, ShockTransform.LEVEL_CHANGE, Decimal("100")),
        (AdhocShockType.PCT_CHANGE, ShockTransform.PCT_CHANGE, Decimal("100")),
    ],
)
def test_adhoc_shock_normalizes_per_transform(shock_type, transform, expected):
    shock = AdhocShock(
        variable=MacroVariable.UNEMPLOYMENT_RATE,
        shock_type=shock_type,
        magnitude=Decimal("100"),
        quarters=[1],
    )
    delta = compute_delta_x(MacroVariable.UNEMPLOYMENT_RATE, 1, transform, None, None, [shock])
    assert delta == expected
