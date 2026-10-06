"""Scenario Reference Store (C27) tests against the real, bootstrapped
illustrative seed data in schemas/011_scenario_reference.sql. See
02-design-document.md §3.4.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from fry14_engine.db import bootstrap, get_connection
from fry14_engine.scenario.models import (
    MacroVariable,
    ScenarioName,
    ScenarioReferenceNotFoundError,
    TranslationTarget,
)
from fry14_engine.scenario.reference_store import ScenarioReferenceStore


@pytest.fixture
def store(tmp_db_path: Path) -> ScenarioReferenceStore:
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    return ScenarioReferenceStore(con)


def test_load_supervisory_scenario_jump_off_and_trough(store: ScenarioReferenceStore):
    scenario = store.load_supervisory_scenario("FED-2026")
    jump_off = scenario.get(ScenarioName.SEVERELY_ADVERSE, 0, MacroVariable.UNEMPLOYMENT_RATE)
    trough = scenario.get(ScenarioName.SEVERELY_ADVERSE, 5, MacroVariable.UNEMPLOYMENT_RATE)
    assert jump_off == Decimal("4.0")
    assert trough == Decimal("10.0")


def test_load_supervisory_scenario_unknown_version_raises(store: ScenarioReferenceStore):
    with pytest.raises(ScenarioReferenceNotFoundError):
        store.load_supervisory_scenario("NONEXISTENT-VERSION")


def test_supervisory_scenario_get_unknown_key_raises(store: ScenarioReferenceStore):
    scenario = store.load_supervisory_scenario("FED-2026")
    with pytest.raises(ScenarioReferenceNotFoundError):
        scenario.get(ScenarioName.BASELINE, 20, MacroVariable.UNEMPLOYMENT_RATE)


def test_load_translation_table_is_approved(store: ScenarioReferenceStore):
    table = store.load_translation_table("1.0.0")
    assert table.is_approved is True
    assert table.multiplier_floor == Decimal("0.5")
    assert table.multiplier_cap == Decimal("5.0")


def test_translation_table_betas_for_small_business_pd(store: ScenarioReferenceStore):
    table = store.load_translation_table("1.0.0")
    betas = table.betas_for("SMALL_BUSINESS", "CRE", TranslationTarget.PD)
    beta, transform = betas[MacroVariable.UNEMPLOYMENT_RATE]
    assert beta == Decimal("0.35")
    assert str(transform) == "LEVEL_CHANGE"


def test_translation_table_betas_for_unknown_segment_is_empty(store: ScenarioReferenceStore):
    table = store.load_translation_table("1.0.0")
    assert table.betas_for("NONEXISTENT_SEGMENT", "CRE", TranslationTarget.PD) == {}


def test_translation_table_grade_scaling(store: ScenarioReferenceStore):
    table = store.load_translation_table("1.0.0")
    assert table.grade_scaling(5) == Decimal("1.167")
    with pytest.raises(ScenarioReferenceNotFoundError):
        table.grade_scaling(99)


def test_load_translation_table_unknown_version_raises(store: ScenarioReferenceStore):
    with pytest.raises(ScenarioReferenceNotFoundError):
        store.load_translation_table("9.9.9")


def test_get_active_translation_table_returns_approved_version(store: ScenarioReferenceStore):
    table = store.get_active_translation_table()
    assert table.version == "1.0.0"
    assert table.is_approved


def test_load_grade_pd_grid(store: ScenarioReferenceStore):
    grid = store.load_grade_pd_grid("1.0.0")
    assert grid.get_pd(1) == Decimal("0.0005")
    assert grid.get_pd(10) == Decimal("0.2000")
    with pytest.raises(ScenarioReferenceNotFoundError):
        grid.get_pd(99)


def test_load_grade_pd_grid_unknown_version_raises(store: ScenarioReferenceStore):
    with pytest.raises(ScenarioReferenceNotFoundError):
        store.load_grade_pd_grid("9.9.9")
