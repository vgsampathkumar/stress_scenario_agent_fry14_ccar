"""Orchestrator run models. See 02-design-document.md §3.11."""

from __future__ import annotations

from dataclasses import dataclass, field

from fry14_engine.aggregation.gateway import AggregationRunResult
from fry14_engine.catalog.gateway import CatalogUpdateResult
from fry14_engine.contracts.validation_gateway import ValidationRunResult
from fry14_engine.ingestion.adapter import IngestionAdapter
from fry14_engine.ingestion.gateway import IngestionRunResult
from fry14_engine.risk_engine.engine import RiskCalculationRunResult


@dataclass
class ChannelSource:
    """One ingestion channel for a single orchestrated run — a batch-file
    drop, an event-stream feed, etc. All channels in the same `run()` call
    share one `pipeline_run_id`, satisfying "a single run, multiple
    sources" end-to-end lineage."""

    adapter: IngestionAdapter
    source_entity_code: str
    source_system_of_record: str


@dataclass
class PipelineRunReport:
    pipeline_run_id: str
    data_product_id: str
    ingestion_results: list[IngestionRunResult] = field(default_factory=list)
    validation: ValidationRunResult | None = None
    risk_calculation: RiskCalculationRunResult | None = None
    aggregation: AggregationRunResult | None = None
    catalog: CatalogUpdateResult | None = None
