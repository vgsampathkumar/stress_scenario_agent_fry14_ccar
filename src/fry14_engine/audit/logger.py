"""Audit Logger (C15): the convenience entry point gateways and services
use to record events, so an entire pipeline run — or an ad-hoc
access-control decision — can be reconstructed later from
`pipeline_run_id` alone. See 02-design-document.md §3.10.
"""

from __future__ import annotations

from typing import Any

import duckdb

from fry14_engine.audit.models import AuditEvent
from fry14_engine.audit.store import AuditLogStore
from fry14_engine.common.enums import AuditEventType
from fry14_engine.common.ids import new_record_id


class AuditLogger:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._store = AuditLogStore(connection)

    def log(
        self,
        event_type: AuditEventType,
        pipeline_run_id: str | None = None,
        actor: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._store.write(
            AuditEvent(
                event_id=new_record_id(),
                pipeline_run_id=pipeline_run_id,
                event_type=str(event_type),
                actor=actor,
                detail=detail,
            )
        )

    def read_run(self, pipeline_run_id: str) -> list[AuditEvent]:
        """Reconstruct every recorded stage of a run, in order."""
        return self._store.read_by_pipeline_run_id(pipeline_run_id)
