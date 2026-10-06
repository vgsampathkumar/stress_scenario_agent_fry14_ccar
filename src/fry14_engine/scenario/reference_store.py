"""Scenario Reference Store (C27): loads Fed supervisory scenarios, the
scenario translation table, and the grade PD grid from the database into
in-memory objects — mirrors `ReferenceDataStore`'s and `ContractRegistry`'s
load/get_active pattern. See 02-design-document.md §3.4.
"""

from __future__ import annotations

import duckdb

from fry14_engine.scenario.models import (
    GradePDGrid,
    MacroVariable,
    ScenarioName,
    ScenarioReferenceNotFoundError,
    ScenarioTranslationTable,
    ShockTransform,
    SupervisoryScenarioSet,
    TranslationTarget,
)


def _semver_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


class ScenarioReferenceStore:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection

    def load_supervisory_scenario(self, scenario_version: str) -> SupervisoryScenarioSet:
        rows = self._connection.execute(
            "SELECT scenario_name, quarter, macro_variable, value "
            "FROM scenario.supervisory_scenario WHERE scenario_version = ?",
            [scenario_version],
        ).fetchall()
        if not rows:
            raise ScenarioReferenceNotFoundError(
                f"No supervisory scenario data for version {scenario_version!r}"
            )
        values = {
            (ScenarioName(name), quarter, MacroVariable(variable)): value
            for name, quarter, variable, value in rows
        }
        return SupervisoryScenarioSet(scenario_version=scenario_version, values=values)

    def list_translation_table_versions(self) -> list[str]:
        rows = self._connection.execute(
            "SELECT version FROM scenario.scenario_translation_table"
        ).fetchall()
        return sorted((row[0] for row in rows), key=_semver_key)

    def load_translation_table(self, version: str) -> ScenarioTranslationTable:
        header = self._connection.execute(
            "SELECT effective_date, status, multiplier_floor, multiplier_cap "
            "FROM scenario.scenario_translation_table WHERE version = ?",
            [version],
        ).fetchone()
        if header is None:
            raise ScenarioReferenceNotFoundError(f"No translation table version {version!r}")
        effective_date, status, multiplier_floor, multiplier_cap = header

        entry_rows = self._connection.execute(
            "SELECT portfolio_segment, asset_class, target, macro_variable, beta, transform "
            "FROM scenario.scenario_translation_entry WHERE version = ?",
            [version],
        ).fetchall()
        betas: dict = {}
        transforms: dict = {}
        for segment, asset_class, target, variable, beta, transform in entry_rows:
            key = (segment, asset_class, TranslationTarget(target), MacroVariable(variable))
            betas[key] = beta
            transforms[key] = ShockTransform(transform)

        sensitivity_rows = self._connection.execute(
            "SELECT grade, pd_scaling FROM scenario.scenario_translation_grade_sensitivity "
            "WHERE version = ?",
            [version],
        ).fetchall()
        grade_sensitivity = dict(sensitivity_rows)

        return ScenarioTranslationTable(
            version=version,
            effective_date=effective_date,
            status=status,
            multiplier_floor=multiplier_floor,
            multiplier_cap=multiplier_cap,
            betas=betas,
            transforms=transforms,
            grade_sensitivity=grade_sensitivity,
        )

    def get_active_translation_table(self) -> ScenarioTranslationTable:
        """The highest-versioned APPROVED table — never a DRAFT one, even
        if a newer DRAFT version exists."""
        versions = self.list_translation_table_versions()
        approved = [v for v in versions if self.load_translation_table(v).is_approved]
        if not approved:
            raise ScenarioReferenceNotFoundError("No APPROVED translation table found")
        return self.load_translation_table(approved[-1])

    def load_grade_pd_grid(self, version: str) -> GradePDGrid:
        rows = self._connection.execute(
            "SELECT grade, pd FROM scenario.grade_pd_grid WHERE version = ?", [version]
        ).fetchall()
        if not rows:
            raise ScenarioReferenceNotFoundError(f"No grade PD grid version {version!r}")
        return GradePDGrid(version=version, pd_by_grade=dict(rows))
