"""Ingestion Gateway: orchestrates a single adapter run through
normalization (already done by the adapter), metadata stamping, and
landing-zone persistence. See 02-design-document.md §3.1.

A full multi-adapter, multi-run orchestration (retries, idempotency across
an entire pipeline) is the Orchestrator's job (C16, Phase 7) — this class
covers exactly one adapter's one `read()` -> stamp -> land cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

from fry14_engine.common.metadata import MetadataStamper
from fry14_engine.ingestion.adapter import IngestionAdapter
from fry14_engine.ingestion.errors import IngestionParseError
from fry14_engine.ingestion.landing_store import LandingStore
from fry14_engine.ingestion.stamped import StampedRecord


@dataclass
class IngestionRunResult:
    pipeline_run_id: str
    records_landed: int
    stamped_records: list[StampedRecord] = field(default_factory=list)
    parse_errors: list[IngestionParseError] = field(default_factory=list)


class IngestionGateway:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._landing_store = LandingStore(connection)

    def run(self, adapter: IngestionAdapter, stamper: MetadataStamper) -> IngestionRunResult:
        batch = adapter.read()
        stamped = [
            StampedRecord(record=record, metadata=stamper.build_metadata())
            for record in batch.records
        ]
        records_landed = self._landing_store.write(stamped)
        return IngestionRunResult(
            pipeline_run_id=stamper.pipeline_run_id,
            records_landed=records_landed,
            stamped_records=stamped,
            parse_errors=batch.parse_errors,
        )
