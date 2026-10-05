"""Governed Store: persists contract-valid, PII-hashed records into
`governed.loan_record`, and reads them back for a pipeline run — the input
the Risk Metric Engine (C10, Phase 4) consumes. See 02-design-document.md
§2.4, §3.3 and schemas/004_governed.sql.
"""

from __future__ import annotations

from typing import Any

import duckdb

from fry14_engine.pii.governed_models import GovernedLoanRecord

_COLUMNS = [
    "governed_id",
    "loan_id",
    "borrower_key_hash",
    "borrower_name_hash",
    "borrower_address_hash",
    "counterparty_id",
    "asset_class",
    "internal_credit_risk_grade",
    "credit_score",
    "outstanding_balance",
    "unadvanced_commitment",
    "maturity_date",
    "probability_of_default",
    "loss_given_default",
    "portfolio_segment",
    "pipeline_run_id",
    "contract_version",
    "ingestion_timestamp",
]

_INSERT_SQL = f"""
    INSERT INTO governed.loan_record ({", ".join(_COLUMNS)})
    VALUES ({", ".join("?" for _ in _COLUMNS)})
"""


class GovernedStore:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection

    def write(self, records: list[GovernedLoanRecord]) -> int:
        if not records:
            return 0
        rows = [self._to_row(record) for record in records]
        self._connection.executemany(_INSERT_SQL, rows)
        return len(rows)

    def read_by_pipeline_run_id(self, pipeline_run_id: str) -> list[GovernedLoanRecord]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM governed.loan_record WHERE pipeline_run_id = ?",
            [pipeline_run_id],
        ).fetchall()
        records = []
        for row in rows:
            data = dict(zip(_COLUMNS, row, strict=True))
            data["governed_id"] = str(data["governed_id"])  # DuckDB UUID column -> uuid.UUID
            records.append(GovernedLoanRecord(**data))
        return records

    @staticmethod
    def _to_row(record: GovernedLoanRecord) -> list[Any]:
        return [
            record.governed_id,
            record.loan_id,
            record.borrower_key_hash,
            record.borrower_name_hash,
            record.borrower_address_hash,
            record.counterparty_id,
            record.asset_class,
            record.internal_credit_risk_grade,
            record.credit_score,
            record.outstanding_balance,
            record.unadvanced_commitment,
            record.maturity_date,
            record.probability_of_default,
            record.loss_given_default,
            record.portfolio_segment,
            record.pipeline_run_id,
            record.contract_version,
            record.ingestion_timestamp,
        ]
