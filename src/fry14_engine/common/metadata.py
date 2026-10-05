"""Operational metadata model and stamping utility.

Implements requirement 2.1 ("Operational Metadata Stamping"): every incoming
record must be tagged with ingestion timestamp, source entity code, pipeline
run identifier, and original system of record before it is written to the
landing zone. See 02-design-document.md §2.1 / §3.1.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from fry14_engine.common.enums import IngestionChannel
from fry14_engine.common.ids import ClockFn, utc_now


class IngestionMetadata(BaseModel):
    """The `_ingestion_metadata` envelope attached to every landed record."""

    model_config = ConfigDict(frozen=True)

    ingestion_timestamp: datetime
    source_entity_code: str = Field(min_length=1)
    pipeline_run_id: str = Field(min_length=1)
    source_system_of_record: str = Field(min_length=1)
    ingestion_channel: IngestionChannel


class MetadataStamper:
    """Stamps raw records with an `IngestionMetadata` envelope.

    A single stamper instance is constructed per pipeline run so that every
    record it stamps shares the same `pipeline_run_id` and ingestion channel.
    Accepts an injectable clock for deterministic testing.
    """

    def __init__(
        self,
        pipeline_run_id: str,
        source_entity_code: str,
        source_system_of_record: str,
        ingestion_channel: IngestionChannel,
        clock: ClockFn = utc_now,
    ) -> None:
        self._pipeline_run_id = pipeline_run_id
        self._source_entity_code = source_entity_code
        self._source_system_of_record = source_system_of_record
        self._ingestion_channel = ingestion_channel
        self._clock = clock

    @property
    def pipeline_run_id(self) -> str:
        return self._pipeline_run_id

    def build_metadata(self) -> IngestionMetadata:
        """Build a fresh, native (non-serialized) `IngestionMetadata`
        instance stamped with the current clock reading. Used by callers
        (e.g. `IngestionGateway`) that need typed values — a `datetime`, not
        an ISO string — for direct persistence."""
        return IngestionMetadata(
            ingestion_timestamp=self._clock(),
            source_entity_code=self._source_entity_code,
            pipeline_run_id=self._pipeline_run_id,
            source_system_of_record=self._source_system_of_record,
            ingestion_channel=self._ingestion_channel,
        )

    def stamp(self, record: dict[str, Any]) -> dict[str, Any]:
        """Return a new dict: the original record plus a populated
        `_ingestion_metadata` key (JSON-serializable). Does not mutate the
        input record."""
        metadata = self.build_metadata()
        return {**record, "_ingestion_metadata": metadata.model_dump(mode="json")}

    def stamp_many(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.stamp(record) for record in records]
