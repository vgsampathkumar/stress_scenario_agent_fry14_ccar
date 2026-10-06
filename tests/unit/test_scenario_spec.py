"""`build_scenario_spec` validator tests. See 02-design-document.md §3.18
step 2 and requirement AG-3.2.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from fry14_engine.db import bootstrap, get_connection
from fry14_engine.scenario.models import (
    ScenarioName,
    ScenarioReferenceNotFoundError,
    ScenarioTableNotApprovedError,
)
from fry14_engine.scenario.reference_store import ScenarioReferenceStore
from fry14_engine.scenario.spec_models import (
    AdhocShock,
    AdhocShockType,
    GradeMigration,
    PortfolioScope,
    ScenarioClassification,
)
from fry14_engine.scenario.spec_validator import ScenarioSpecValidationError, build_scenario_spec

_TRANSLATION_VERSION = "1.0.0"
_PARAMETER_VERSION = "1.0.0"


@pytest.fixture
def store(tmp_db_path: Path) -> ScenarioReferenceStore:
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    con.execute(
        "INSERT INTO scenario.scenario_translation_table "
        "(version, effective_date, status, multiplier_floor, multiplier_cap) "
        "VALUES ('9.9.9-draft', DATE '2026-01-01', 'DRAFT', 0.5, 5.0)"
    )
    return ScenarioReferenceStore(con)


def _scope() -> PortfolioScope:
    return PortfolioScope(reporting_period="2026-06")


def test_build_scenario_spec_supervisory_success(store: ScenarioReferenceStore):
    spec = build_scenario_spec(
        store,
        requested_by="risk.analyst@example.com",
        portfolio_scope=_scope(),
        translation_table_version=_TRANSLATION_VERSION,
        regulatory_parameter_version=_PARAMETER_VERSION,
        base_scenario=ScenarioName.SEVERELY_ADVERSE,
        supervisory_scenario_version="FED-2026",
    )
    assert spec.classification == ScenarioClassification.SUPERVISORY
    assert spec.status == "DRAFT"
    assert spec.scenario_spec_id


def test_build_scenario_spec_with_adhoc_shock_is_exploratory(store: ScenarioReferenceStore):
    spec = build_scenario_spec(
        store,
        requested_by="risk.analyst@example.com",
        portfolio_scope=_scope(),
        translation_table_version=_TRANSLATION_VERSION,
        regulatory_parameter_version=_PARAMETER_VERSION,
        adhoc_shocks=[
            AdhocShock(
                variable="UNEMPLOYMENT_RATE",
                shock_type=AdhocShockType.ADD_PCT_POINTS,
                magnitude=Decimal("2"),
                quarters=[1, 2],
            )
        ],
    )
    assert spec.classification == ScenarioClassification.EXPLORATORY


def test_build_scenario_spec_with_grade_migration_is_exploratory(store: ScenarioReferenceStore):
    spec = build_scenario_spec(
        store,
        requested_by="risk.analyst@example.com",
        portfolio_scope=_scope(),
        translation_table_version=_TRANSLATION_VERSION,
        regulatory_parameter_version=_PARAMETER_VERSION,
        grade_migration=GradeMigration(notches=2),
    )
    assert spec.classification == ScenarioClassification.EXPLORATORY


def test_unapproved_translation_table_is_rejected(store: ScenarioReferenceStore):
    with pytest.raises(ScenarioTableNotApprovedError):
        build_scenario_spec(
            store,
            requested_by="risk.analyst@example.com",
            portfolio_scope=_scope(),
            translation_table_version="9.9.9-draft",
            regulatory_parameter_version=_PARAMETER_VERSION,
        )


def test_unknown_translation_table_version_raises(store: ScenarioReferenceStore):
    with pytest.raises(ScenarioReferenceNotFoundError):
        build_scenario_spec(
            store,
            requested_by="risk.analyst@example.com",
            portfolio_scope=_scope(),
            translation_table_version="9.9.9-missing",
            regulatory_parameter_version=_PARAMETER_VERSION,
        )


def test_missing_requested_by_raises(store: ScenarioReferenceStore):
    with pytest.raises(ScenarioSpecValidationError) as exc_info:
        build_scenario_spec(
            store,
            requested_by="",
            portfolio_scope=_scope(),
            translation_table_version=_TRANSLATION_VERSION,
            regulatory_parameter_version=_PARAMETER_VERSION,
        )
    assert exc_info.value.reason_code == "SCENARIO_SPEC_INVALID"


@pytest.mark.parametrize("horizon_quarters", [0, 10, -1])
def test_horizon_quarters_out_of_range_raises(store: ScenarioReferenceStore, horizon_quarters):
    with pytest.raises(ScenarioSpecValidationError):
        build_scenario_spec(
            store,
            requested_by="risk.analyst@example.com",
            portfolio_scope=_scope(),
            translation_table_version=_TRANSLATION_VERSION,
            regulatory_parameter_version=_PARAMETER_VERSION,
            horizon_quarters=horizon_quarters,
        )


@pytest.mark.parametrize("reporting_period", ["2026", "2026/06", "26-06", "2026-6"])
def test_bad_reporting_period_format_raises(store: ScenarioReferenceStore, reporting_period):
    with pytest.raises(ScenarioSpecValidationError):
        build_scenario_spec(
            store,
            requested_by="risk.analyst@example.com",
            portfolio_scope=PortfolioScope(reporting_period=reporting_period),
            translation_table_version=_TRANSLATION_VERSION,
            regulatory_parameter_version=_PARAMETER_VERSION,
        )


def test_base_scenario_without_supervisory_version_raises(store: ScenarioReferenceStore):
    with pytest.raises(ScenarioSpecValidationError):
        build_scenario_spec(
            store,
            requested_by="risk.analyst@example.com",
            portfolio_scope=_scope(),
            translation_table_version=_TRANSLATION_VERSION,
            regulatory_parameter_version=_PARAMETER_VERSION,
            base_scenario=ScenarioName.SEVERELY_ADVERSE,
        )


def test_base_scenario_missing_quarters_raises(store: ScenarioReferenceStore):
    store._connection.execute(
        "INSERT INTO scenario.supervisory_scenario "
        "(scenario_version, scenario_name, quarter, macro_variable, value) "
        "VALUES ('SHORT-HORIZON', 'SEVERELY_ADVERSE', 0, 'UNEMPLOYMENT_RATE', 4.0)"
    )
    with pytest.raises(ScenarioSpecValidationError):
        build_scenario_spec(
            store,
            requested_by="risk.analyst@example.com",
            portfolio_scope=_scope(),
            translation_table_version=_TRANSLATION_VERSION,
            regulatory_parameter_version=_PARAMETER_VERSION,
            base_scenario=ScenarioName.SEVERELY_ADVERSE,
            supervisory_scenario_version="SHORT-HORIZON",
            horizon_quarters=9,
        )


@pytest.mark.parametrize(
    ("shock_type", "magnitude"),
    [
        (AdhocShockType.ADD_BPS, Decimal("5000")),
        (AdhocShockType.ADD_PCT_POINTS, Decimal("50")),
        (AdhocShockType.PCT_CHANGE, Decimal("10")),
    ],
)
def test_adhoc_shock_magnitude_out_of_bounds_raises(store, shock_type, magnitude):
    with pytest.raises(ScenarioSpecValidationError):
        build_scenario_spec(
            store,
            requested_by="risk.analyst@example.com",
            portfolio_scope=_scope(),
            translation_table_version=_TRANSLATION_VERSION,
            regulatory_parameter_version=_PARAMETER_VERSION,
            adhoc_shocks=[
                AdhocShock(
                    variable="UNEMPLOYMENT_RATE",
                    shock_type=shock_type,
                    magnitude=magnitude,
                    quarters=[1],
                )
            ],
        )


def test_adhoc_shock_empty_quarters_raises(store: ScenarioReferenceStore):
    with pytest.raises(ScenarioSpecValidationError):
        build_scenario_spec(
            store,
            requested_by="risk.analyst@example.com",
            portfolio_scope=_scope(),
            translation_table_version=_TRANSLATION_VERSION,
            regulatory_parameter_version=_PARAMETER_VERSION,
            adhoc_shocks=[
                AdhocShock(
                    variable="UNEMPLOYMENT_RATE",
                    shock_type=AdhocShockType.ADD_PCT_POINTS,
                    magnitude=Decimal("2"),
                    quarters=[],
                )
            ],
        )


def test_adhoc_shock_quarter_outside_horizon_raises(store: ScenarioReferenceStore):
    with pytest.raises(ScenarioSpecValidationError):
        build_scenario_spec(
            store,
            requested_by="risk.analyst@example.com",
            portfolio_scope=_scope(),
            translation_table_version=_TRANSLATION_VERSION,
            regulatory_parameter_version=_PARAMETER_VERSION,
            horizon_quarters=4,
            adhoc_shocks=[
                AdhocShock(
                    variable="UNEMPLOYMENT_RATE",
                    shock_type=AdhocShockType.ADD_PCT_POINTS,
                    magnitude=Decimal("2"),
                    quarters=[5],
                )
            ],
        )


@pytest.mark.parametrize("notches", [10, -10])
def test_grade_migration_notches_out_of_range_raises(store: ScenarioReferenceStore, notches):
    with pytest.raises(ScenarioSpecValidationError):
        build_scenario_spec(
            store,
            requested_by="risk.analyst@example.com",
            portfolio_scope=_scope(),
            translation_table_version=_TRANSLATION_VERSION,
            regulatory_parameter_version=_PARAMETER_VERSION,
            grade_migration=GradeMigration(notches=notches),
        )
