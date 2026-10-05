"""Maturity bucketing: converts a loan's remaining time to maturity, as of
a reporting period's end date, into one of four buckets. See
02-design-document.md §3.5.
"""

from __future__ import annotations

import calendar
from datetime import date

from fry14_engine.common.enums import MaturityBucket


def reporting_period_end_date(reporting_period: str) -> date:
    """`reporting_period` is 'YYYY-MM'; returns the last calendar day of
    that month."""
    year_str, month_str = reporting_period.split("-")
    year, month = int(year_str), int(month_str)
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)


def months_remaining(as_of: date, maturity_date: date) -> int:
    """Whole months from `as_of` to `maturity_date`. Already-matured loans
    (maturity on or before `as_of`) return 0 rather than a negative number —
    there's no "overdue" bucket in this model."""
    if maturity_date <= as_of:
        return 0
    months = (maturity_date.year - as_of.year) * 12 + (maturity_date.month - as_of.month)
    if maturity_date.day < as_of.day:
        months -= 1
    return max(months, 0)


def bucket_for_months_remaining(months: int) -> MaturityBucket:
    if months <= 12:
        return MaturityBucket.M_0_12
    if months <= 36:
        return MaturityBucket.M_13_36
    if months <= 60:
        return MaturityBucket.M_37_60
    return MaturityBucket.M_60_PLUS


def maturity_bucket(reporting_period: str, maturity_date: date) -> MaturityBucket:
    as_of = reporting_period_end_date(reporting_period)
    return bucket_for_months_remaining(months_remaining(as_of, maturity_date))
