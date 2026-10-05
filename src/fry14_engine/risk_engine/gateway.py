"""Risk Calculation Gateway: loads the active regulatory parameter set,
runs the (pure) Risk Metric Engine over a batch of governed records, and
persists both the computed metrics and any calculation exceptions. See
02-design-document.md §3.5.
"""

from __future__ import annotations

import duckdb

from fry14_engine.pii.governed_models import GovernedLoanRecord
from fry14_engine.reference_data.store import ReferenceDataStore
from fry14_engine.risk_engine.engine import RiskCalculationRunResult, RiskMetricEngine
from fry14_engine.risk_engine.store import RiskMetricsStore


class RiskCalculationGateway:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._reference_data_store = ReferenceDataStore(connection)
        self._metrics_store = RiskMetricsStore(connection)

    def run(
        self,
        governed_records: list[GovernedLoanRecord],
        reporting_period: str,
        pipeline_run_id: str,
    ) -> RiskCalculationRunResult:
        parameter_set = self._reference_data_store.get_active()
        engine = RiskMetricEngine(parameter_set)
        result = engine.run(governed_records, reporting_period, pipeline_run_id)

        self._metrics_store.write_metrics(result.metrics)
        self._metrics_store.write_exceptions(result.exceptions)

        return result
