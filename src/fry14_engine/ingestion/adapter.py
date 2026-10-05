"""Common interface for all source adapters (batch file, event stream, ...).

Each adapter is responsible only for normalizing its source-specific payload
shape into `RawLoanRecord` — metadata stamping and landing-zone persistence
are handled uniformly downstream by `IngestionGateway` / `LandingStore`. See
02-design-document.md §3.1 (Ingestion Gateway).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from fry14_engine.common.enums import IngestionChannel
from fry14_engine.ingestion.errors import IngestionParseError
from fry14_engine.ingestion.models import RawLoanRecord


@dataclass
class IngestionBatch:
    records: list[RawLoanRecord] = field(default_factory=list)
    parse_errors: list[IngestionParseError] = field(default_factory=list)


class IngestionAdapter(ABC):
    channel: IngestionChannel
    source_system_of_record: str

    @abstractmethod
    def read(self) -> IngestionBatch:
        """Fetch and normalize all currently-available records from the source."""
        raise NotImplementedError

    def _normalize_into(self, payload: dict, batch: IngestionBatch) -> None:
        """Normalize a single raw payload into `batch`. A malformed payload
        is recorded as a parse error rather than raised, so one bad payload
        never aborts the rest of the read()."""
        try:
            merged = {"source_system_of_record": self.source_system_of_record, **payload}
            batch.records.append(RawLoanRecord.model_validate(merged))
        except Exception as exc:  # noqa: BLE001 - any coercion failure becomes a parse error
            batch.parse_errors.append(IngestionParseError(raw_payload=payload, error=str(exc)))
