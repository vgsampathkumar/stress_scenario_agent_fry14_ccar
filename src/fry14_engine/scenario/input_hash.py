"""`input_hash` computation: a hash of a `ScenarioSpec`'s *content* (not its
randomly-generated `scenario_spec_id`) plus the base pipeline run and
reference versions used, so two independently-built specs with identical
parameters hash identically — "replay with the same input_hash gives
identical output" (03-implementation-plan.md Phase 8). See
02-design-document.md §2.10.
"""

from __future__ import annotations

import hashlib
import json

from fry14_engine.scenario.spec_models import ScenarioSpec


def compute_input_hash(spec: ScenarioSpec, base_pipeline_run_id: str) -> str:
    canonical = {
        "base_scenario": str(spec.base_scenario) if spec.base_scenario else None,
        "supervisory_scenario_version": spec.supervisory_scenario_version,
        "portfolio_scope": spec.portfolio_scope.model_dump(mode="json"),
        "adhoc_shocks": [s.model_dump(mode="json") for s in spec.adhoc_shocks],
        "grade_migration": (
            spec.grade_migration.model_dump(mode="json") if spec.grade_migration else None
        ),
        "horizon_quarters": spec.horizon_quarters,
        "translation_table_version": spec.translation_table_version,
        "regulatory_parameter_version": spec.regulatory_parameter_version,
        "base_pipeline_run_id": base_pipeline_run_id,
    }
    canonical_json = json.dumps(canonical, sort_keys=True, default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
