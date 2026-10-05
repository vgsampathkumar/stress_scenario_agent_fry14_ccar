"""Quarantine Store (C6) writer: persists rejected records with reason
codes into `quarantine.quarantine_record`. Append-only, same as the landing
store — a remediation changes `remediation_status` via a dedicated update,
never a blanket rewrite of the row. See 02-design-document.md §2.3, §3.2.
"""

from __future__ import annotations

import json

import duckdb

from fry14_engine.quarantine.models import QuarantineRecord

_INSERT_SQL = """
    INSERT INTO quarantine.quarantine_record
        (quarantine_id, loan_id, pipeline_run_id, contract_id, contract_version,
         original_record, exception_reason_codes, rejected_at, remediation_status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        self._connection.executemany(_INSERT_SQL, rows)
        return len(rows)
