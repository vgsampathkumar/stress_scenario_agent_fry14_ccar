from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fry14_engine.catalog.health import compute_health_score, compute_sla_status
from fry14_engine.common.enums import SlaStatus

NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)


def test_on_time_within_window():
    last_completed = NOW - timedelta(hours=1)
    assert compute_sla_status(last_completed, NOW, sla_window_hours=24) == SlaStatus.ON_TIME


def test_on_time_exactly_at_window_boundary():
    last_completed = NOW - timedelta(hours=24)
    assert compute_sla_status(last_completed, NOW, sla_window_hours=24) == SlaStatus.ON_TIME


def test_at_risk_just_past_window():
    last_completed = NOW - timedelta(hours=24, minutes=1)
    assert compute_sla_status(last_completed, NOW, sla_window_hours=24) == SlaStatus.AT_RISK


def test_at_risk_exactly_at_multiplier_boundary():
    last_completed = NOW - timedelta(hours=48)
    assert (
        compute_sla_status(last_completed, NOW, sla_window_hours=24, at_risk_multiplier=2.0)
        == SlaStatus.AT_RISK
    )


def test_breached_past_multiplier_window():
    last_completed = NOW - timedelta(hours=48, minutes=1)
    assert (
        compute_sla_status(last_completed, NOW, sla_window_hours=24, at_risk_multiplier=2.0)
        == SlaStatus.BREACHED
    )


def test_breached_long_stale():
    last_completed = NOW - timedelta(days=30)
    assert compute_sla_status(last_completed, NOW) == SlaStatus.BREACHED


@pytest.mark.parametrize(
    "sla_status,expected",
    [
        (SlaStatus.ON_TIME, Decimal("100.00")),
        (SlaStatus.AT_RISK, Decimal("85.00")),
        (SlaStatus.BREACHED, Decimal("70.00")),
    ],
)
def test_health_score_weighted_formula_at_perfect_dq(sla_status, expected):
    # 100% DQ: score = 100*0.7 + sla_score*0.3
    assert compute_health_score(Decimal("100.00"), sla_status) == expected


def test_health_score_weighted_formula_at_zero_dq():
    # 0% DQ, ON_TIME SLA: score = 0*0.7 + 100*0.3 = 30
    assert compute_health_score(Decimal("0.00"), SlaStatus.ON_TIME) == Decimal("30.00")


def test_health_score_zero_when_dq_zero_and_breached():
    assert compute_health_score(Decimal("0.00"), SlaStatus.BREACHED) == Decimal("0.00")


def test_health_score_is_quantized_to_two_decimals():
    score = compute_health_score(Decimal("83.333"), SlaStatus.ON_TIME)
    assert score == score.quantize(Decimal("0.01"))
