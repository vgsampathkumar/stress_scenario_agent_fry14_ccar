"""Schedule Aggregate model — the final data product this phase produces.
See 02-design-document.md §2.7 and schemas/007_aggregates.sql.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from fry14_engine.common.enums import MaturityBucket


class ScheduleAggregate(BaseModel):
    model_config = ConfigDict(frozen=True)

    reporting_period: str
    portfolio_segment: str
    credit_rating_grade: int
    remaining_maturity_bucket: MaturityBucket
    total_ead: Decimal
    total_el: Decimal
    total_rwa: Decimal
    loan_count: int
    schema_version: str
    pipeline_run_id: str
