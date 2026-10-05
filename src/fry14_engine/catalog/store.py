"""Data Product Catalog store: upserts the per-product catalog entry and
appends to its schema version history. See 02-design-document.md §3.7 and
schemas/008_catalog.sql.
"""

from __future__ import annotations

import duckdb

from fry14_engine.catalog.models import DataProductCatalogEntry, SchemaVersionHistoryEntry

_ENTRY_COLUMNS = [
    "data_product_id",
    "health_score",
    "dq_pass_percentage",
    "sla_status",
    "last_run_id",
    "owner",
]

_ENTRY_UPSERT_SQL = f"""
    INSERT INTO catalog.data_product_catalog_entry ({", ".join(_ENTRY_COLUMNS)})
    VALUES ({", ".join("?" for _ in _ENTRY_COLUMNS)})
    ON CONFLICT (data_product_id) DO UPDATE SET
        health_score = excluded.health_score,
        dq_pass_percentage = excluded.dq_pass_percentage,
        sla_status = excluded.sla_status,
        last_run_id = excluded.last_run_id,
        owner = excluded.owner,
        last_updated_at = now()
"""

_HISTORY_COLUMNS = ["data_product_id", "version", "effective_date", "changelog"]

_HISTORY_INSERT_SQL = f"""
    INSERT INTO catalog.schema_version_history ({", ".join(_HISTORY_COLUMNS)})
    VALUES ({", ".join("?" for _ in _HISTORY_COLUMNS)})
    ON CONFLICT (data_product_id, version) DO NOTHING
"""


class CatalogStore:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection

    def upsert_entry(self, entry: DataProductCatalogEntry) -> None:
        self._connection.execute(
            _ENTRY_UPSERT_SQL,
            [
                entry.data_product_id,
                entry.health_score,
                entry.dq_pass_percentage,
                str(entry.sla_status),
                entry.last_run_id,
                entry.owner,
            ],
        )

    def get_entry(self, data_product_id: str) -> DataProductCatalogEntry | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_ENTRY_COLUMNS)} FROM catalog.data_product_catalog_entry "
            "WHERE data_product_id = ?",
            [data_product_id],
        ).fetchone()
        if row is None:
            return None
        return DataProductCatalogEntry(**dict(zip(_ENTRY_COLUMNS, row, strict=True)))

    def record_schema_version(self, entry: SchemaVersionHistoryEntry) -> None:
        """Append-only: a version already recorded for this data product is
        left untouched (first-seen effective_date is preserved)."""
        self._connection.execute(
            _HISTORY_INSERT_SQL,
            [entry.data_product_id, entry.version, entry.effective_date, entry.changelog],
        )

    def get_schema_version_history(self, data_product_id: str) -> list[SchemaVersionHistoryEntry]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_HISTORY_COLUMNS)} FROM catalog.schema_version_history "
            "WHERE data_product_id = ? ORDER BY effective_date",
            [data_product_id],
        ).fetchall()
        return [
            SchemaVersionHistoryEntry(**dict(zip(_HISTORY_COLUMNS, row, strict=True)))
            for row in rows
        ]
