"""Catalog Gateway: updates a data product's catalog entry after a
pipeline run completes — DQ %, SLA status (freshness-based), health score —
and records the output schema version it produced. See
02-design-document.md §3.7.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import duckdb

from fry14_engine.catalog.health import compute_health_score, compute_sla_status
from fry14_engine.catalog.models import DataProductCatalogEntry, SchemaVersionHistoryEntry
from fry14_engine.catalog.store import CatalogStore
from fry14_engine.common.ids import ClockFn, utc_now

DEFAULT_OWNER = "Data Engineering"


@dataclass
class CatalogUpdateResult:
    entry: DataProductCatalogEntry


class CatalogGateway:
    def __init__(self, connection: duckdb.DuckDBPyConnection, clock: ClockFn = utc_now) -> None:
        self._store = CatalogStore(connection)
        self._clock = clock

    def update_after_run(
        self,
        data_product_id: str,
        pipeline_run_id: str,
        dq_pass_percentage: float,
        run_completed_at: datetime,
        output_schema_version: str,
        output_schema_effective_date: date,
        owner: str = DEFAULT_OWNER,
    ) -> CatalogUpdateResult:
        dq_pass_percentage_decimal = Decimal(str(round(dq_pass_percentage, 4)))
        now = self._clock()
        sla_status = compute_sla_status(run_completed_at, now)
        health_score = compute_health_score(dq_pass_percentage_decimal, sla_status)

        entry = DataProductCatalogEntry(
            data_product_id=data_product_id,
            health_score=health_score,
            dq_pass_percentage=dq_pass_percentage_decimal,
            sla_status=sla_status,
            last_run_id=pipeline_run_id,
            owner=owner,
        )
        self._store.upsert_entry(entry)
        self._store.record_schema_version(
            SchemaVersionHistoryEntry(
                data_product_id=data_product_id,
                version=output_schema_version,
                effective_date=output_schema_effective_date,
            )
        )

        return CatalogUpdateResult(entry=entry)

    def get_entry(self, data_product_id: str) -> DataProductCatalogEntry | None:
        return self._store.get_entry(data_product_id)

    def get_schema_version_history(self, data_product_id: str) -> list[SchemaVersionHistoryEntry]:
        return self._store.get_schema_version_history(data_product_id)
