"""`build_scenario_spec`: the deterministic validator AG-3 calls after
drafting a spec from a natural-language request (Phase 11). Checks bounds,
scope, reference-data versions, and sets `classification`. Never touches
an LLM. See 02-design-document.md §3.18 step 2 and requirement AG-3.2.

Note on `CALC_SCENARIO_VARIABLE_MISSING` (design doc §6 catalog): this
validator does not raise it. A macro variable the translation table has a
beta for, but that has no supervisory/ad-hoc data at run time, contributes
zero to the shock (same "never fail-stop" fail-forward principle used
everywhere else in this project) rather than erroring — there is no
plausible way to reach that reason code with this implementation, so it
stays reserved in the catalog rather than wired to dead code.
"""

from __future__ import annotations

import re
from decimal import Decimal

from fry14_engine.common.ids import new_record_id
from fry14_engine.scenario.models import ScenarioName, ScenarioTableNotApprovedError
from fry14_engine.scenario.reference_store import ScenarioReferenceStore
from fry14_engine.scenario.spec_models import (
    AdhocShock,
    AdhocShockType,
    GradeMigration,
    PortfolioScope,
    ScenarioClassification,
    ScenarioSpec,
    ScenarioSpecStatus,
)

_REPORTING_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")

_ADHOC_MAGNITUDE_BOUNDS: dict[AdhocShockType, tuple[Decimal, Decimal]] = {
    AdhocShockType.ADD_BPS: (Decimal("-1000"), Decimal("1000")),
    AdhocShockType.ADD_PCT_POINTS: (Decimal("-20"), Decimal("20")),
    AdhocShockType.PCT_CHANGE: (Decimal("-0.9"), Decimal("5.0")),
}


class ScenarioSpecValidationError(Exception):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


def build_scenario_spec(
    reference_store: ScenarioReferenceStore,
    requested_by: str,
    portfolio_scope: PortfolioScope,
    translation_table_version: str,
    regulatory_parameter_version: str,
    base_scenario: ScenarioName | None = None,
    supervisory_scenario_version: str | None = None,
    adhoc_shocks: list[AdhocShock] | None = None,
    grade_migration: GradeMigration | None = None,
    horizon_quarters: int = 9,
    source_request_text: str | None = None,
) -> ScenarioSpec:
    adhoc_shocks = adhoc_shocks or []

    if not requested_by:
        raise ScenarioSpecValidationError("SCENARIO_SPEC_INVALID", "requested_by is required")

    if not 1 <= horizon_quarters <= 9:
        raise ScenarioSpecValidationError(
            "SCENARIO_SPEC_INVALID", f"horizon_quarters must be 1-9, got {horizon_quarters}"
        )

    if not _REPORTING_PERIOD_RE.match(portfolio_scope.reporting_period):
        raise ScenarioSpecValidationError(
            "SCENARIO_SPEC_INVALID",
            f"portfolio_scope.reporting_period must be 'YYYY-MM', got "
            f"{portfolio_scope.reporting_period!r}",
        )

    translation_table = reference_store.load_translation_table(translation_table_version)
    if not translation_table.is_approved:
        raise ScenarioTableNotApprovedError(
            f"Translation table version {translation_table_version!r} has status "
            f"{translation_table.status!r}, not APPROVED"
        )

    if base_scenario is not None:
        if not supervisory_scenario_version:
            raise ScenarioSpecValidationError(
                "SCENARIO_SPEC_INVALID",
                "supervisory_scenario_version is required when base_scenario is set",
            )
        supervisory_set = reference_store.load_supervisory_scenario(supervisory_scenario_version)
        available_quarters = {
            q for (name, q, _v) in supervisory_set.values if name == base_scenario
        }
        missing_quarters = set(range(0, horizon_quarters + 1)) - available_quarters
        if missing_quarters:
            raise ScenarioSpecValidationError(
                "SCENARIO_SPEC_INVALID",
                f"{base_scenario} under {supervisory_scenario_version!r} is missing quarters "
                f"{sorted(missing_quarters)} (horizon requires 0-{horizon_quarters})",
            )

    for shock in adhoc_shocks:
        lo, hi = _ADHOC_MAGNITUDE_BOUNDS[shock.shock_type]
        if not lo <= shock.magnitude <= hi:
            raise ScenarioSpecValidationError(
                "SCENARIO_SPEC_INVALID",
                f"{shock.shock_type} magnitude {shock.magnitude} outside plausible bounds "
                f"[{lo}, {hi}]",
            )
        if not shock.quarters:
            raise ScenarioSpecValidationError(
                "SCENARIO_SPEC_INVALID", "ad-hoc shock must specify at least one quarter"
            )
        if any(not 1 <= q <= horizon_quarters for q in shock.quarters):
            raise ScenarioSpecValidationError(
                "SCENARIO_SPEC_INVALID",
                f"ad-hoc shock quarters {shock.quarters} must be within 1-{horizon_quarters}",
            )

    if grade_migration is not None and not -9 <= grade_migration.notches <= 9:
        raise ScenarioSpecValidationError(
            "SCENARIO_SPEC_INVALID",
            f"grade_migration.notches {grade_migration.notches} outside plausible range [-9, 9]",
        )

    classification = (
        ScenarioClassification.EXPLORATORY
        if (adhoc_shocks or grade_migration is not None)
        else ScenarioClassification.SUPERVISORY
    )

    return ScenarioSpec(
        scenario_spec_id=new_record_id(),
        source_request_text=source_request_text,
        base_scenario=base_scenario,
        supervisory_scenario_version=supervisory_scenario_version,
        portfolio_scope=portfolio_scope,
        adhoc_shocks=adhoc_shocks,
        grade_migration=grade_migration,
        horizon_quarters=horizon_quarters,
        translation_table_version=translation_table_version,
        regulatory_parameter_version=regulatory_parameter_version,
        classification=classification,
        status=ScenarioSpecStatus.DRAFT,
        requested_by=requested_by,
    )
