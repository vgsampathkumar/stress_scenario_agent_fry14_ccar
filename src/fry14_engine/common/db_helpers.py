"""Bulk-insert helper.

DuckDB's Python `executemany` has very high per-call overhead — measured
at roughly 100x slower than a single multi-row `INSERT ... VALUES
(...),(...),...` for row counts in the low thousands (a real bottleneck
caught by the Phase 7 performance smoke test: 2,000 rows took ~8 seconds
via `executemany` versus ~0.03s via one statement). Every store that
writes more than one row at a time should use this helper instead.
"""

from __future__ import annotations

from typing import Any

import duckdb


def execute_bulk_insert(
    connection: duckdb.DuckDBPyConnection,
    sql_template: str,
    rows: list[list[Any]],
) -> None:
    """`sql_template` must contain exactly one `{values}` placeholder
    marking where the comma-separated row tuples go, e.g.:

        f"INSERT INTO t (a, b) VALUES {{values}} ON CONFLICT (a) DO UPDATE ..."

    Every row in `rows` must have the same length (the column count). A
    single statement is built with one `(?, ?, ...)` group per row and all
    values passed as flattened, parameterized bind values — never
    string-interpolated, so this is exactly as injection-safe as
    `executemany`, just not row-at-a-time.
    """
    if not rows:
        return
    row_width = len(rows[0])
    group = "(" + ",".join(["?"] * row_width) + ")"
    placeholders = ",".join([group] * len(rows))
    flat_params = [value for row in rows for value in row]
    connection.execute(sql_template.format(values=placeholders), flat_params)
