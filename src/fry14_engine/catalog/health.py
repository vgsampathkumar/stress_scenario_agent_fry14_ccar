"""Health score and SLA status computation (C12): a transparent, documented
formula, not a black box. See 02-design-document.md §3.7.

SLA status is freshness-based: it compares how long ago a data product's
last run completed against a configured window. This *is* "freshness" per
the design doc's own definition ("SLA status... computed by comparing run
completion time against a configured SLA window"), so health_score only
needs to combine DQ pass rate and SLA status — folding in a separate
freshness term would double-count the same signal.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from fry14_engine.common.enums import SlaStatus

DEFAULT_SLA_WINDOW_HOURS = 24.0
DEFAULT_AT_RISK_MULTIPLIER = 2.0

# Illustrative weights, not a regulatory requirement — DQ pass rate matters
# more than SLA timeliness, but a stale product still can't be fully healthy.
_DQ_WEIGHT = Decimal("0.7")
_SLA_WEIGHT = Decimal("0.3")

_SLA_STATUS_SCORE: dict[SlaStatus, Decimal] = {
    SlaStatus.ON_TIME: Decimal(100),
    SlaStatus.AT_RISK: Decimal(50),
    SlaStatus.BREACHED: Decimal(0),
}


def compute_sla_status(
    last_completed_at: datetime,
    as_of: datetime,
    sla_window_hours: float = DEFAULT_SLA_WINDOW_HOURS,
    at_risk_multiplier: float = DEFAULT_AT_RISK_MULTIPLIER,
) -> SlaStatus:
    """ON_TIME if the last run completed within `sla_window_hours` of
    `as_of`; AT_RISK within `at_risk_multiplier` x that window; BREACHED
    beyond it."""
    age = as_of - last_completed_at
    if age <= timedelta(hours=sla_window_hours):
        return SlaStatus.ON_TIME
    if age <= timedelta(hours=sla_window_hours * at_risk_multiplier):
        return SlaStatus.AT_RISK
    return SlaStatus.BREACHED


def compute_health_score(dq_pass_percentage: Decimal, sla_status: SlaStatus) -> Decimal:
    """Weighted composite: 70% data quality pass rate, 30% SLA adherence."""
    sla_score = _SLA_STATUS_SCORE[sla_status]
    score = dq_pass_percentage * _DQ_WEIGHT + sla_score * _SLA_WEIGHT
    return score.quantize(Decimal("0.01"))
