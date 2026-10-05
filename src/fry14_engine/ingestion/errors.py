"""Structural ingestion failures — distinct from contract-validation
quarantine (Phase 2). A parse error means the payload could not be coerced
into `RawLoanRecord` at all (e.g. non-numeric garbage in a numeric field);
a quarantine record means it coerced fine but violates a business rule."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IngestionParseError:
    raw_payload: dict[str, Any]
    error: str
