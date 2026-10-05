from __future__ import annotations

from datetime import date

import pytest

from fry14_engine.common.enums import MaturityBucket
from fry14_engine.risk_engine.maturity import (
    bucket_for_months_remaining,
    maturity_bucket,
    months_remaining,
    reporting_period_end_date,
)


def test_reporting_period_end_date_handles_31_day_month():
    assert reporting_period_end_date("2026-01") == date(2026, 1, 31)


def test_reporting_period_end_date_handles_leap_february():
    assert reporting_period_end_date("2028-02") == date(2028, 2, 29)


def test_reporting_period_end_date_handles_non_leap_february():
    assert reporting_period_end_date("2026-02") == date(2026, 2, 28)


def test_months_remaining_exact_year():
    as_of = date(2026, 1, 31)
    assert months_remaining(as_of, date(2027, 1, 31)) == 12


def test_months_remaining_already_matured_returns_zero():
    as_of = date(2026, 1, 31)
    assert months_remaining(as_of, date(2025, 1, 1)) == 0
    assert months_remaining(as_of, as_of) == 0


def test_months_remaining_partial_month_rounds_down():
    as_of = date(2026, 1, 31)
    # one day short of a full 12 months -> 11 whole months
    assert months_remaining(as_of, date(2027, 1, 30)) == 11


@pytest.mark.parametrize(
    "months,expected",
    [
        (0, MaturityBucket.M_0_12),
        (12, MaturityBucket.M_0_12),
        (13, MaturityBucket.M_13_36),
        (36, MaturityBucket.M_13_36),
        (37, MaturityBucket.M_37_60),
        (60, MaturityBucket.M_37_60),
        (61, MaturityBucket.M_60_PLUS),
        (120, MaturityBucket.M_60_PLUS),
    ],
)
def test_bucket_boundaries(months, expected):
    assert bucket_for_months_remaining(months) == expected


def test_maturity_bucket_end_to_end():
    assert maturity_bucket("2026-01", date(2027, 6, 30)) == MaturityBucket.M_13_36
