"""Audit Log Store: append-only writer/reader for `audit.event_log`. See
02-design-document.md §3.10 and schemas/010_audit.sql.
"""

from __future__ import annotations

import json

import duckdb

from fry14_engine.audit.models import AuditEvent

_INSERT_SQL = """
    INSERT INTO audit.event_log (event_id, pipeline_run_id, event_type, actor, detail)
    VALUES (?, ?, ?, ?, ?)
"""


class AuditLogStore:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection

    def write(self, event: AuditEvent) -> None:
        self._connection.execute(
            _INSERT_SQL,
            [
                event.event_id,
                event.pipeline_run_id,
                event.event_type,
                event.actor,
                json.dumps(event.detail) if event.detail is not None else None,
            ],
        )

    def read_by_pipeline_run_id(self, pipeline_run_id: str) -> list[AuditEvent]:
        rows = self._connection.execute(
            "SELECT event_id, pipeline_run_id, event_type, actor, detail "
            "FROM audit.event_log WHERE pipeline_run_id = ? ORDER BY occurred_at",
            [pipeline_run_id],
        ).fetchall()
        return [self._to_event(row) for row in rows]

    @staticmethod
    def _to_event(row: tuple) -> AuditEvent:
        event_id, pipeline_run_id, event_type, actor, detail_json = row
        return AuditEvent(
            event_id=str(event_id),  # DuckDB UUID column -> uuid.UUID
            pipeline_run_id=pipeline_run_id,
            event_type=event_type,
            actor=actor,
            detail=json.loads(detail_json) if detail_json else None,
        )
