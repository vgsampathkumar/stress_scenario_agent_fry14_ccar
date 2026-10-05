"""Landing Store writer: persists metadata-stamped records into the
immutable, append-only `landing.raw_loan_record` table. See
02-design-document.md §2.1/§3.1 and schemas/001_landing.sql.

No update/delete methods are exposed by design — corrections arrive as new
records under a new `pipeline_run_id`, never as mutations of landed rows.
"""

from __future__ import annotations

from typing import Any

import duckdb

from fry14_engine.common.ids import new_record_id
from fry14_engine.ingestion.stamped import StampedRecord

_COLUMNS = [
    "landing_id",
    "loan_id",
    "borrower_tax_id",
    "borrower_legal_name",
    "borrower_address",
    "counterparty_id",
    "asset_class",
    "internal_credit_risk_grade",
    "credit_score",
    "outstanding_balance",
    "unadvanced_commitment",
    "origination_date",
    "maturity_date",
    "probability_of_default",
    "loss_given_default",
    "portfolio_segment",
    "source_system_of_record",
    "ingestion_timestamp",
    "source_entity_code",
    "pipeline_run_id",
    "ingestion_channel",
]

_INSERT_SQL = f"""
    INSERT INTO landing.raw_loan_record ({", ".join(_COLUMNS)})
    VALUES ({", ".join("?" for _ in _COLUMNS)})
"""


class LandingStore:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection

    def write(self, stamped_records: list[StampedRecord]) -> int:
        """Insert stamped records. Returns the number of rows written."""
        if not stamped_records:
            return 0
        rows = [self._to_row(stamped) for stamped in stamped_records]
        self._connection.executemany(_INSERT_SQL, rows)
        return len(rows)

    @staticmethod
    def _to_row(stamped: StampedRecord) -> list[Any]:
        record, meta = stamped.record, stamped.metadata
        return [
            new_record_id(),
            record.loan_id,
            record.borrower_tax_id,
            record.borrower_legal_name,
            record.borrower_address,
            record.counterparty_id,
            record.asset_class,
            record.internal_credit_risk_grade,
            record.credit_score,
            record.outstanding_balance,
            record.unadvanced_commitment,
            record.origination_date,
            record.maturity_date,
            record.probability_of_default,
            record.loss_given_default,
            record.portfolio_segment,
            record.source_system_of_record,
            meta.ingestion_timestamp,
            meta.source_entity_code,
            meta.pipeline_run_id,
            str(meta.ingestion_channel),
        ]
