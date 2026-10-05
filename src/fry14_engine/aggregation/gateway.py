"""Aggregation Gateway: reads the risk metrics produced by a risk
calculation run, groups them into `ScheduleAggregate` rows, and upserts
the result. See 02-design-document.md §3.6.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

from fry14_engine.aggregation.engine import AGGREGATE_SCHEMA_VERSION, AggregationEngine
from fry14_engine.aggregation.models import ScheduleAggregate
from fry14_engine.aggregation.store import AggregationStore
from fry14_engine.risk_engine.store import RiskMetricsStore


@dataclass
class AggregationRunResult:
    pipeline_run_id: str
    schema_version: str
    input_metric_count: int
    aggregates: list[ScheduleAggregate] = field(default_factory=list)


class AggregationGateway:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._metrics_store = RiskMetricsStore(connection)
        self._aggregation_store = AggregationStore(connection)

    def run(
        self, pipeline_run_id: str, schema_version: str = AGGREGATE_SCHEMA_VERSION
    ) -> AggregationRunResult:
        """`pipeline_run_id` identifies the risk-calculation run whose
        `LoanRiskMetrics` get aggregated — the resulting aggregate rows are
        stamped with that same id for lineage."""
        metrics = self._metrics_store.read_by_pipeline_run_id(pipeline_run_id)
        engine = AggregationEngine(schema_version)
        aggregates = engine.run(metrics, pipeline_run_id)

        self._aggregation_store.upsert(aggregates)

        return AggregationRunResult(
            pipeline_run_id=pipeline_run_id,
            schema_version=schema_version,
            input_metric_count=len(metrics),
            aggregates=aggregates,
        )
