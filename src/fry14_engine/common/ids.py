"""ID and timestamp generation utilities.

Centralized here so every component gets `pipeline_run_id`s and timestamps the
same way — important for reproducibility and lineage (see 02-design-document.md §3.11).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

ClockFn = Callable[[], datetime]


def utc_now() -> datetime:
    """Current UTC time, timezone-aware. The default clock for the system."""
    return datetime.now(UTC)


def new_pipeline_run_id() -> str:
    """Generate a new unique identifier for a single orchestrated pipeline run.

    One `pipeline_run_id` is generated per run and threaded through every
    record stamped during that run (ingestion, validation, quarantine,
    calculation, aggregation) so the whole run can be reconstructed from
    lineage/audit logs alone.
    """
    return str(uuid.uuid4())


def new_record_id() -> str:
    """Generate a unique identifier for a single record-level entity
    (e.g. a quarantine_id)."""
    return str(uuid.uuid4())
