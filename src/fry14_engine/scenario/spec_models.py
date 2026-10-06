"""`ScenarioSpec` and its nested structures. See 02-design-document.md
§2.10 and schemas/012_scenario_runs.sql.

Phase 8 is deterministic-only — there is no natural-language parsing here
(that's AG-3's job, Phase 11). A `ScenarioSpec` in this phase is always
constructed directly (by a test, or eventually by the agent after it has
already resolved any ambiguity via a clarifying question), then validated
by `build_scenario_spec`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from fry14_engine.scenario.models import MacroVariable, ScenarioName


class AdhocShockType(StrEnum):
    ADD_BPS = "ADD_BPS"
    ADD_PCT_POINTS = "ADD_PCT_POINTS"
    PCT_CHANGE = "PCT_CHANGE"


class ScenarioClassification(StrEnum):
    SUPERVISORY = "SUPERVISORY"
    EXPLORATORY = "EXPLORATORY"


class ScenarioSpecStatus(StrEnum):
    DRAFT = "DRAFT"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    CONFIRMED = "CONFIRMED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"


class PortfolioScope(BaseModel):
    model_config = ConfigDict(frozen=True)

    reporting_period: str  # 'YYYY-MM' of the governed base data
    portfolio_segments: list[str] | None = None  # null = all
    asset_classes: list[str] | None = None
    credit_grades: list[int] | None = None


class AdhocShock(BaseModel):
    model_config = ConfigDict(frozen=True)

    variable: MacroVariable
    shock_type: AdhocShockType
    magnitude: Decimal
    quarters: list[int]  # subset of 1..horizon_quarters


class GradeMigration(BaseModel):
    model_config = ConfigDict(frozen=True)

    notches: int  # positive = downgrade (worse), negative = upgrade (better)
    segments: list[str] | None = None  # null = all


class ScenarioSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_spec_id: str
    source_request_text: str | None = None
    base_scenario: ScenarioName | None = None  # None means base_scenario == "NONE"
    supervisory_scenario_version: str | None = None
    portfolio_scope: PortfolioScope
    adhoc_shocks: list[AdhocShock] = []
    grade_migration: GradeMigration | None = None
    horizon_quarters: int = 9
    translation_table_version: str
    regulatory_parameter_version: str
    classification: ScenarioClassification
    status: ScenarioSpecStatus = ScenarioSpecStatus.DRAFT
    requested_by: str
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
