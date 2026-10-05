"""Computed risk metric and calculation-exception models. See
02-design-document.md §2.6 and schemas/006_metrics.sql.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from fry14_engine.common.enums import MaturityBucket


class LoanRiskMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    loan_id: str
    reporting_period: str
    ead: Decimal
    el: Decimal
    rwa: Decimal
    asset_class: str
    portfolio_segment: str
    credit_rating_grade: int
    remaining_maturity_bucket: MaturityBucket
    calc_engine_version: str
    regulatory_parameter_version: str
    pipeline_run_id: str


class CalculationException(BaseModel):
    model_config = ConfigDict(frozen=True)

    exception_id: str
    loan_id: str
    pipeline_run_id: str
    reason_code: str
    detail: str | None = None
