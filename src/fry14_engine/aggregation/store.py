"""Schedule Aggregate store: upserts `ScheduleAggregate` rows. Re-aggregating
the same (reporting_period, portfolio_segment, credit_rating_grade,
remaining_maturity_bucket, schema_version) key overwrites cleanly rather
than erroring on the primary key — "idempotent re-aggregation" per
requirement 2.4 / the Phase 5 plan. A new `schema_version` for the same
period is a distinct, retained row (schema version history), not an
overwrite of the old one. See 02-design-document.md §3.6 and
schemas/007_aggregates.sql.
"""

from __future__ import annotations

import duckdb

from fry14_engine.aggregation.models import ScheduleAggregate
from fry14_engine.common.db_helpers import execute_bulk_insert

_COLUMNS = [
    "reporting_period",
    "portfolio_segment",
    "credit_rating_grade",
    "remaining_maturity_bucket",
    "total_ead",
    "total_el",
    "total_rwa",
    "loan_count",
    "schema_version",
    "pipeline_run_id",
]

_UPSERT_SQL_TEMPLATE = f"""
    INSERT INTO aggregates.schedule_aggregate ({", ".join(_COLUMNS)})
    VALUES {{values}}
    ON CONFLICT (reporting_period, portfolio_segment, credit_rating_grade,
                 remaining_maturity_bucket, schema_version)
    DO UPDATE SET
        total_ead = excluded.total_ead,
        total_el = excluded.total_el,
        total_rwa = excluded.total_rwa,
        loan_count = excluded.loan_count,
        pipeline_run_id = excluded.pipeline_run_id,
        generated_at = now()
"""


class AggregationStore:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection

    def upsert(self, aggregates: list[ScheduleAggregate]) -> int:
        if not aggregates:
            return 0
        rows = [
            [
                a.reporting_period,
                a.portfolio_segment,
                a.credit_rating_grade,
                str(a.remaining_maturity_bucket),
                a.total_ead,
                a.total_el,
                a.total_rwa,
                a.loan_count,
                a.schema_version,
                a.pipeline_run_id,
            ]
            for a in aggregates
        ]
        execute_bulk_insert(self._connection, _UPSERT_SQL_TEMPLATE, rows)
        return len(rows)

    def read_by_reporting_period(
        self, reporting_period: str, schema_version: str
    ) -> list[ScheduleAggregate]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM aggregates.schedule_aggregate "
            "WHERE reporting_period = ? AND schema_version = ?",
            [reporting_period, schema_version],
        ).fetchall()
        return [ScheduleAggregate(**dict(zip(_COLUMNS, row, strict=True))) for row in rows]
