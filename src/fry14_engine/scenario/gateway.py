"""Stress Scenario Gateway: the single entry point for running a governed
scenario end-to-end, with no LLM involved (03-implementation-plan.md Phase
8). Persists the `ScenarioSpec`, loads the governed loans and baseline risk
metrics for its `base_pipeline_run_id`, loads the scenario reference data
the spec names, runs the Stress Engine (C28), and persists the
`ScenarioRunResult`. See 02-design-document.md §3.18.
"""

from __future__ import annotations

import duckdb

from fry14_engine.audit.logger import AuditLogger
from fry14_engine.common.enums import AuditEventType
from fry14_engine.pii.governed_store import GovernedStore
from fry14_engine.reference_data.store import ReferenceDataStore
from fry14_engine.risk_engine.store import RiskMetricsStore
from fry14_engine.scenario.engine import StressEngine
from fry14_engine.scenario.reference_store import ScenarioReferenceStore
from fry14_engine.scenario.run_models import ScenarioRunResult
from fry14_engine.scenario.run_store import ScenarioRunStore
from fry14_engine.scenario.spec_models import ScenarioSpec
from fry14_engine.scenario.spec_store import ScenarioSpecStore


class StressScenarioGateway:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._governed_store = GovernedStore(connection)
        self._metrics_store = RiskMetricsStore(connection)
        self._reference_data_store = ReferenceDataStore(connection)
        self._scenario_reference_store = ScenarioReferenceStore(connection)
        self._spec_store = ScenarioSpecStore(connection)
        self._run_store = ScenarioRunStore(connection)
        self._audit_logger = AuditLogger(connection)

    def run(self, spec: ScenarioSpec, base_pipeline_run_id: str) -> ScenarioRunResult:
        self._spec_store.write(spec)
        self._audit_logger.log(
            AuditEventType.STRESS_SCENARIO,
            pipeline_run_id=base_pipeline_run_id,
            actor=spec.requested_by,
            detail={"stage": "spec_persisted", "scenario_spec_id": spec.scenario_spec_id},
        )

        governed_loans = self._governed_store.read_by_pipeline_run_id(base_pipeline_run_id)
        baseline_metrics = {
            m.loan_id: m for m in self._metrics_store.read_by_pipeline_run_id(base_pipeline_run_id)
        }

        parameter_set = self._reference_data_store.load(spec.regulatory_parameter_version)
        translation_table = self._scenario_reference_store.load_translation_table(
            spec.translation_table_version
        )
        supervisory = (
            self._scenario_reference_store.load_supervisory_scenario(
                spec.supervisory_scenario_version
            )
            if spec.supervisory_scenario_version
            else None
        )
        # The grade-PD grid is published as part of the same scenario reference
        # bundle as the translation table (both versioned together), so it
        # shares that version rather than the (unrelated) CCF/risk-weight
        # parameter_version.
        grade_pd_grid = (
            self._scenario_reference_store.load_grade_pd_grid(spec.translation_table_version)
            if spec.grade_migration is not None
            else None
        )

        engine = StressEngine(translation_table, parameter_set, supervisory, grade_pd_grid)
        result = engine.run(spec, governed_loans, baseline_metrics, base_pipeline_run_id)

        self._run_store.write_result(result)
        self._audit_logger.log(
            AuditEventType.STRESS_SCENARIO,
            pipeline_run_id=base_pipeline_run_id,
            actor=spec.requested_by,
            detail={
                "stage": "run_persisted",
                "scenario_run_id": result.scenario_run_id,
                "classification": result.classification,
                "loan_quarter_count": len(result.stressed_loan_metrics),
            },
        )
        return result
