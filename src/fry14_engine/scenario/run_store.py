"""Scenario Run Store: persists and reads back `ScenarioRunResult`,
`StressedLoanMetrics`, and `ScenarioComparisonRow` rows. See
schemas/012_scenario_runs.sql.
"""

from __future__ import annotations

import duckdb

from fry14_engine.common.db_helpers import execute_bulk_insert
from fry14_engine.scenario.run_models import (
    ScenarioComparisonRow,
    ScenarioRunResult,
    StressedLoanMetrics,
)

_RESULT_INSERT_SQL = """
    INSERT INTO scenario.scenario_run_result
        (scenario_run_id, scenario_spec_id, base_pipeline_run_id, input_hash,
         stress_engine_version, translation_table_version, regulatory_parameter_version,
         classification, projected_loss_9q)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_RESULT_COLUMNS = [
    "scenario_run_id",
    "scenario_spec_id",
    "base_pipeline_run_id",
    "input_hash",
    "stress_engine_version",
    "translation_table_version",
    "regulatory_parameter_version",
    "classification",
    "projected_loss_9q",
]

_STRESSED_COLUMNS = [
    "scenario_run_id",
    "loan_id",
    "quarter",
    "pd_stressed",
    "lgd_stressed",
    "ccf_stressed",
    "ead_stressed",
    "el_stressed",
    "rwa_stressed",
]
_STRESSED_INSERT_SQL_TEMPLATE = f"""
    INSERT INTO scenario.stressed_loan_metrics ({", ".join(_STRESSED_COLUMNS)})
    VALUES {{values}}
"""

_COMPARISON_COLUMNS = [
    "scenario_run_id",
    "quarter",
    "portfolio_segment",
    "credit_rating_grade",
    "ead_base",
    "ead_stressed",
    "el_base",
    "el_stressed",
    "rwa_base",
    "rwa_stressed",
    "loan_count",
]
_COMPARISON_INSERT_SQL_TEMPLATE = f"""
    INSERT INTO scenario.scenario_comparison ({", ".join(_COMPARISON_COLUMNS)})
    VALUES {{values}}
"""


class ScenarioRunStore:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection

    def write_result(self, result: ScenarioRunResult) -> None:
        self._connection.execute(
            _RESULT_INSERT_SQL,
            [
                result.scenario_run_id,
                result.scenario_spec_id,
                result.base_pipeline_run_id,
                result.input_hash,
                result.stress_engine_version,
                result.translation_table_version,
                result.regulatory_parameter_version,
                result.classification,
                result.projected_loss_9q,
            ],
        )
        self._write_stressed_metrics(result.stressed_loan_metrics)
        self._write_comparison_rows(result.comparison_rows)

    def _write_stressed_metrics(self, rows: list[StressedLoanMetrics]) -> None:
        if not rows:
            return
        values = [
            [
                r.scenario_run_id,
                r.loan_id,
                r.quarter,
                r.pd_stressed,
                r.lgd_stressed,
                r.ccf_stressed,
                r.ead_stressed,
                r.el_stressed,
                r.rwa_stressed,
            ]
            for r in rows
        ]
        execute_bulk_insert(self._connection, _STRESSED_INSERT_SQL_TEMPLATE, values)

    def _write_comparison_rows(self, rows: list[ScenarioComparisonRow]) -> None:
        if not rows:
            return
        values = [
            [
                r.scenario_run_id,
                r.quarter,
                r.portfolio_segment,
                r.credit_rating_grade,
                r.ead_base,
                r.ead_stressed,
                r.el_base,
                r.el_stressed,
                r.rwa_base,
                r.rwa_stressed,
                r.loan_count,
            ]
            for r in rows
        ]
        execute_bulk_insert(self._connection, _COMPARISON_INSERT_SQL_TEMPLATE, values)

    def read_result(self, scenario_run_id: str) -> ScenarioRunResult | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_RESULT_COLUMNS)} FROM scenario.scenario_run_result "
            "WHERE scenario_run_id = ?",
            [scenario_run_id],
        ).fetchone()
        if row is None:
            return None
        data = dict(zip(_RESULT_COLUMNS, row, strict=True))
        return ScenarioRunResult(
            scenario_run_id=data["scenario_run_id"],
            scenario_spec_id=data["scenario_spec_id"],
            base_pipeline_run_id=data["base_pipeline_run_id"],
            input_hash=data["input_hash"],
            stress_engine_version=data["stress_engine_version"],
            translation_table_version=data["translation_table_version"],
            regulatory_parameter_version=data["regulatory_parameter_version"],
            classification=data["classification"],
            stressed_loan_metrics=self.read_stressed_metrics(scenario_run_id),
            comparison_rows=self.read_comparison_rows(scenario_run_id),
            projected_loss_9q=data["projected_loss_9q"],
        )

    def read_comparison_rows(self, scenario_run_id: str) -> list[ScenarioComparisonRow]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_COMPARISON_COLUMNS)} FROM scenario.scenario_comparison "
            "WHERE scenario_run_id = ? ORDER BY quarter, portfolio_segment, credit_rating_grade",
            [scenario_run_id],
        ).fetchall()
        return [
            ScenarioComparisonRow(**dict(zip(_COMPARISON_COLUMNS, row, strict=True)))
            for row in rows
        ]

    def read_stressed_metrics(self, scenario_run_id: str) -> list[StressedLoanMetrics]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_STRESSED_COLUMNS)} FROM scenario.stressed_loan_metrics "
            "WHERE scenario_run_id = ? ORDER BY loan_id, quarter",
            [scenario_run_id],
        ).fetchall()
        return [
            StressedLoanMetrics(**dict(zip(_STRESSED_COLUMNS, row, strict=True))) for row in rows
        ]
