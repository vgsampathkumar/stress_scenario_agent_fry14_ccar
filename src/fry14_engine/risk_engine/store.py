"""Risk metrics store: persists and reads back `LoanRiskMetrics` and
`CalculationException` rows. See schemas/006_metrics.sql.
"""

from __future__ import annotations

import duckdb

from fry14_engine.risk_engine.models import CalculationException, LoanRiskMetrics

_METRICS_COLUMNS = [
    "loan_id",
    "reporting_period",
    "ead",
    "el",
    "rwa",
    "asset_class",
    "portfolio_segment",
    "credit_rating_grade",
    "remaining_maturity_bucket",
    "calc_engine_version",
    "regulatory_parameter_version",
    "pipeline_run_id",
]

_METRICS_INSERT_SQL = f"""
    INSERT INTO metrics.loan_risk_metrics ({", ".join(_METRICS_COLUMNS)})
    VALUES ({", ".join("?" for _ in _METRICS_COLUMNS)})
"""

_EXCEPTION_INSERT_SQL = """
    INSERT INTO metrics.calculation_exception
        (exception_id, loan_id, pipeline_run_id, reason_code, detail)
    VALUES (?, ?, ?, ?, ?)
"""


class RiskMetricsStore:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection

    def write_metrics(self, metrics: list[LoanRiskMetrics]) -> int:
        if not metrics:
            return 0
        rows = [
            [
                m.loan_id,
                m.reporting_period,
                m.ead,
                m.el,
                m.rwa,
                m.asset_class,
                m.portfolio_segment,
                m.credit_rating_grade,
                str(m.remaining_maturity_bucket),
                m.calc_engine_version,
                m.regulatory_parameter_version,
                m.pipeline_run_id,
            ]
            for m in metrics
        ]
        self._connection.executemany(_METRICS_INSERT_SQL, rows)
        return len(rows)

    def read_by_pipeline_run_id(self, pipeline_run_id: str) -> list[LoanRiskMetrics]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_METRICS_COLUMNS)} FROM metrics.loan_risk_metrics "
            "WHERE pipeline_run_id = ?",
            [pipeline_run_id],
        ).fetchall()
        return [LoanRiskMetrics(**dict(zip(_METRICS_COLUMNS, row, strict=True))) for row in rows]

    def write_exceptions(self, exceptions: list[CalculationException]) -> int:
        if not exceptions:
            return 0
        rows = [
            [e.exception_id, e.loan_id, e.pipeline_run_id, e.reason_code, e.detail]
            for e in exceptions
        ]
        self._connection.executemany(_EXCEPTION_INSERT_SQL, rows)
        return len(rows)
