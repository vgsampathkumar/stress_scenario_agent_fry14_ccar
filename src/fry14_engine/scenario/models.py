"""Scenario Reference Store (C27) models: Fed supervisory scenarios, the
scenario translation table, and the grade PD grid, loaded once into
in-memory objects the (pure) Stress Engine uses — mirrors
`RegulatoryParameterSet` (reference_data/models.py) and `DataContract`
(contracts/models.py): load from DB, then compute against an in-memory
snapshot, never query per loan. See 02-design-document.md §2.10, §3.4.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class MacroVariable(StrEnum):
    UNEMPLOYMENT_RATE = "UNEMPLOYMENT_RATE"
    REAL_GDP_GROWTH = "REAL_GDP_GROWTH"
    CRE_PRICE_INDEX = "CRE_PRICE_INDEX"
    HOUSE_PRICE_INDEX = "HOUSE_PRICE_INDEX"
    TREASURY_3M = "TREASURY_3M"
    TREASURY_10Y = "TREASURY_10Y"
    BBB_CORPORATE_YIELD = "BBB_CORPORATE_YIELD"


class ScenarioName(StrEnum):
    BASELINE = "BASELINE"
    SEVERELY_ADVERSE = "SEVERELY_ADVERSE"


class TranslationTarget(StrEnum):
    PD = "PD"
    LGD = "LGD"
    DRAWDOWN = "DRAWDOWN"


class ShockTransform(StrEnum):
    LEVEL_CHANGE = "LEVEL_CHANGE"
    PCT_CHANGE = "PCT_CHANGE"


class ScenarioReferenceNotFoundError(Exception):
    pass


class ScenarioTableNotApprovedError(Exception):
    """Raised when a draft `ScenarioSpec` references a translation table
    version whose status isn't APPROVED. See requirements.md §3.3 (no tool
    may use unapproved reference data) and the catalog code
    `SCENARIO_TABLE_NOT_APPROVED`."""


@dataclass(frozen=True)
class SupervisoryScenarioSet:
    """All macro-variable paths for every (scenario_name, quarter) under
    one `scenario_version`."""

    scenario_version: str
    values: dict[tuple[ScenarioName, int, MacroVariable], Decimal]

    def get(self, scenario_name: ScenarioName, quarter: int, variable: MacroVariable) -> Decimal:
        try:
            return self.values[(scenario_name, quarter, variable)]
        except KeyError:
            raise ScenarioReferenceNotFoundError(
                f"No value for {scenario_name}/{variable} at quarter {quarter} "
                f"under scenario version {self.scenario_version!r}"
            ) from None


@dataclass(frozen=True)
class ScenarioTranslationTable:
    version: str
    effective_date: date
    status: str  # 'DRAFT' | 'APPROVED'
    multiplier_floor: Decimal
    multiplier_cap: Decimal
    # (portfolio_segment, asset_class, target, variable) -> beta
    betas: dict[tuple[str, str, TranslationTarget, MacroVariable], Decimal]
    transforms: dict[tuple[str, str, TranslationTarget, MacroVariable], ShockTransform]
    grade_sensitivity: dict[int, Decimal]

    @property
    def is_approved(self) -> bool:
        return self.status == "APPROVED"

    def betas_for(
        self, portfolio_segment: str, asset_class: str, target: TranslationTarget
    ) -> dict[MacroVariable, tuple[Decimal, ShockTransform]]:
        """Every (variable -> (beta, transform)) entry defined for this
        segment/asset_class/target. An empty result means that
        target has no driver for this segment/asset_class — contributes 0,
        not an error."""
        result: dict[MacroVariable, tuple[Decimal, ShockTransform]] = {}
        for (segment, asset, tgt, variable), beta in self.betas.items():
            if (segment, asset, tgt) == (portfolio_segment, asset_class, target):
                result[variable] = (beta, self.transforms[(segment, asset, tgt, variable)])
        return result

    def grade_scaling(self, grade: int) -> Decimal:
        try:
            return self.grade_sensitivity[grade]
        except KeyError:
            raise ScenarioReferenceNotFoundError(
                f"No grade sensitivity for grade {grade} under translation table "
                f"version {self.version!r}"
            ) from None


@dataclass(frozen=True)
class GradePDGrid:
    version: str
    pd_by_grade: dict[int, Decimal]

    def get_pd(self, grade: int) -> Decimal:
        try:
            return self.pd_by_grade[grade]
        except KeyError:
            raise ScenarioReferenceNotFoundError(
                f"No PD grid entry for grade {grade} under version {self.version!r}"
            ) from None
