"""Quarantine Store (C6) writer: persists rejected records with reason
codes into `quarantine.quarantine_record`. Append-only, same as the landing
store — a remediation changes `remediation_status` via a dedicated update,
never a blanket rewrite of the row. See 02-design-document.md §2.3, §3.2.
"""

from __future__ import annotations

import json

import duckdb

from fry14_engine.common.db_helpers import execute_bulk_insert
from fry14_engine.common.enums import RemediationStatus
from fry14_engine.quarantine.models import QuarantineRecord

_COLUMNS = [
    "quarantine_id",
    "loan_id",
    "pipeline_run_id",
    "contract_id",
    "contract_version",
    "original_record",
    "exception_reason_codes",
    "rejected_at",
    "remediation_status",
]

_INSERT_SQL_TEMPLATE = f"""
    INSERT INTO quarantine.quarantine_record ({", ".join(_COLUMNS)})
    VALUES {{values}}
"""


class QuarantineStore:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection

    def write(self, records: list[QuarantineRecord]) -> int:
        if not records:
            return 0
        rows = [
            [
                record.quarantine_id,
                record.loan_id,
                record.pipeline_run_id,
                record.contract_id,
                record.contract_version,
                json.dumps(record.original_record),
                json.dumps(list(record.exception_reason_codes)),
                record.rejected_at,
                str(record.remediation_status),
            ]
            for record in records
        ]
        execute_bulk_insert(self._connection, _INSERT_SQL_TEMPLATE, rows)
        return len(rows)

    def read_all(self) -> list[QuarantineRecord]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM quarantine.quarantine_record"
        ).fetchall()
        return [self._to_model(row) for row in rows]

    def read_open_by_reason_code(self, reason_code: str) -> list[QuarantineRecord]:
        # Filtered in Python rather than via a DuckDB JSON-array predicate:
        # quarantine volumes are small (exceptions, not the main record
        # stream), and this keeps the query trivially correct.
        rows = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM quarantine.quarantine_record "
            "WHERE remediation_status = 'OPEN'"
        ).fetchall()
        records = [self._to_model(row) for row in rows]
        return [r for r in records if reason_code in r.exception_reason_codes]

    def read_by_id(self, quarantine_id: str) -> QuarantineRecord | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM quarantine.quarantine_record "
            "WHERE quarantine_id = ?",
            [quarantine_id],
        ).fetchone()
        return self._to_model(row) if row is not None else None

    def update_remediation_status(self, quarantine_id: str, status: RemediationStatus) -> None:
        self._connection.execute(
            "UPDATE quarantine.quarantine_record SET remediation_status = ? "
            "WHERE quarantine_id = ?",
            [str(status), quarantine_id],
        )

    @staticmethod
    def _to_model(row: tuple) -> QuarantineRecord:
        data = dict(zip(_COLUMNS, row, strict=True))
        data["quarantine_id"] = str(data["quarantine_id"])  # DuckDB UUID column -> uuid.UUID
        data["original_record"] = json.loads(data["original_record"])
        data["exception_reason_codes"] = tuple(json.loads(data["exception_reason_codes"]))
        data["remediation_status"] = RemediationStatus(data["remediation_status"])
        return QuarantineRecord(**data)
