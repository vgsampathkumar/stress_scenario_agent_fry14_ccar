"""Aggregation Engine (C11): groups computed risk metrics into
`ScheduleAggregate` rows by reporting period x portfolio segment x credit
grade x maturity bucket. Pure and DB-free, same shape as
`RiskMetricEngine` operating on an already-loaded input list. See
02-design-document.md §3.6 and requirement 2.4 ("Schedule Aggregations").
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from fry14_engine.aggregation.models import ScheduleAggregate
from fry14_engine.common.enums import MaturityBucket
from fry14_engine.risk_engine.models import LoanRiskMetrics

AGGREGATE_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class _GroupKey:
    reporting_period: str
    portfolio_segment: str
    credit_rating_grade: int
    remaining_maturity_bucket: MaturityBucket


class AggregationEngine:
    def __init__(self, schema_version: str = AGGREGATE_SCHEMA_VERSION) -> None:
        self._schema_version = schema_version

    def run(self, metrics: list[LoanRiskMetrics], pipeline_run_id: str) -> list[ScheduleAggregate]:
        groups: dict[_GroupKey, list[LoanRiskMetrics]] = defaultdict(list)
        for metric in metrics:
            key = _GroupKey(
                reporting_period=metric.reporting_period,
                portfolio_segment=metric.portfolio_segment,
                credit_rating_grade=metric.credit_rating_grade,
                remaining_maturity_bucket=metric.remaining_maturity_bucket,
            )
            groups[key].append(metric)

        return [
            ScheduleAggregate(
                reporting_period=key.reporting_period,
                portfolio_segment=key.portfolio_segment,
                credit_rating_grade=key.credit_rating_grade,
                remaining_maturity_bucket=key.remaining_maturity_bucket,
                total_ead=sum((row.ead for row in rows), start=Decimal("0")),
                total_el=sum((row.el for row in rows), start=Decimal("0")),
                total_rwa=sum((row.rwa for row in rows), start=Decimal("0")),
                loan_count=len(rows),
                schema_version=self._schema_version,
                pipeline_run_id=pipeline_run_id,
            )
            for key, rows in groups.items()
        ]
