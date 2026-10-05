"""Pairing of a normalized record with its ingestion metadata, ready for
landing-zone persistence. See 02-design-document.md §2.1."""

from __future__ import annotations

from dataclasses import dataclass

from fry14_engine.common.metadata import IngestionMetadata
from fry14_engine.ingestion.models import RawLoanRecord


@dataclass(frozen=True)
class StampedRecord:
    record: RawLoanRecord
    metadata: IngestionMetadata
