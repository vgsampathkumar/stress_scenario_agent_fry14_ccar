"""Scenario Spec Store: persists and reads back `ScenarioSpec` rows. See
schemas/012_scenario_runs.sql.
"""

from __future__ import annotations

import json

import duckdb

from fry14_engine.scenario.models import ScenarioName
from fry14_engine.scenario.spec_models import (
    AdhocShock,
    GradeMigration,
    PortfolioScope,
    ScenarioClassification,
    ScenarioSpec,
    ScenarioSpecStatus,
)

_COLUMNS = [
    "scenario_spec_id",
    "source_request_text",
    "base_scenario",
    "supervisory_scenario_version",
    "reporting_period",
    "portfolio_scope",
    "adhoc_shocks",
    "grade_migration",
    "horizon_quarters",
    "translation_table_version",
    "regulatory_parameter_version",
    "classification",
    "status",
    "requested_by",
    "confirmed_by",
    "confirmed_at",
]

_INSERT_SQL = f"""
    INSERT INTO scenario.scenario_spec ({", ".join(_COLUMNS)})
    VALUES ({", ".join("?" for _ in _COLUMNS)})
"""


class ScenarioSpecStore:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection

    def write(self, spec: ScenarioSpec) -> None:
        self._connection.execute(
            _INSERT_SQL,
            [
                spec.scenario_spec_id,
                spec.source_request_text,
                str(spec.base_scenario) if spec.base_scenario else "NONE",
                spec.supervisory_scenario_version,
                spec.portfolio_scope.reporting_period,
                json.dumps(spec.portfolio_scope.model_dump(mode="json")),
                json.dumps([s.model_dump(mode="json") for s in spec.adhoc_shocks]),
                (
                    json.dumps(spec.grade_migration.model_dump(mode="json"))
                    if spec.grade_migration
                    else None
                ),
                spec.horizon_quarters,
                spec.translation_table_version,
                spec.regulatory_parameter_version,
                str(spec.classification),
                str(spec.status),
                spec.requested_by,
                spec.confirmed_by,
                spec.confirmed_at,
            ],
        )

    def read(self, scenario_spec_id: str) -> ScenarioSpec | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM scenario.scenario_spec WHERE scenario_spec_id = ?",
            [scenario_spec_id],
        ).fetchone()
        if row is None:
            return None
        data = dict(zip(_COLUMNS, row, strict=True))

        base_scenario = (
            None if data["base_scenario"] == "NONE" else ScenarioName(data["base_scenario"])
        )
        portfolio_scope = PortfolioScope(**json.loads(data["portfolio_scope"]))
        adhoc_shocks = (
            [AdhocShock(**s) for s in json.loads(data["adhoc_shocks"])]
            if data["adhoc_shocks"]
            else []
        )
        grade_migration = (
            GradeMigration(**json.loads(data["grade_migration"]))
            if data["grade_migration"]
            else None
        )

        return ScenarioSpec(
            scenario_spec_id=data["scenario_spec_id"],
            source_request_text=data["source_request_text"],
            base_scenario=base_scenario,
            supervisory_scenario_version=data["supervisory_scenario_version"],
            portfolio_scope=portfolio_scope,
            adhoc_shocks=adhoc_shocks,
            grade_migration=grade_migration,
            horizon_quarters=data["horizon_quarters"],
            translation_table_version=data["translation_table_version"],
            regulatory_parameter_version=data["regulatory_parameter_version"],
            classification=ScenarioClassification(data["classification"]),
            status=ScenarioSpecStatus(data["status"]),
            requested_by=data["requested_by"],
            confirmed_by=data["confirmed_by"],
            confirmed_at=data["confirmed_at"],
        )
