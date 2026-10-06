from __future__ import annotations

import duckdb
import pytest

from fry14_engine.common.db_helpers import execute_bulk_insert


@pytest.fixture
def con():
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val VARCHAR)")
    yield connection
    connection.close()


def test_inserts_all_rows(con):
    rows = [[i, f"val-{i}"] for i in range(50)]
    execute_bulk_insert(con, "INSERT INTO t (id, val) VALUES {values}", rows)
    count = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    assert count == 50


def test_empty_rows_is_a_no_op(con):
    execute_bulk_insert(con, "INSERT INTO t (id, val) VALUES {values}", [])
    count = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    assert count == 0


def test_values_are_parameterized_not_interpolated(con):
    """A value containing SQL-special characters must be inserted
    literally, not executed — proof there's no string-building of values
    anywhere in the helper."""
    rows = [[1, "robert'); DROP TABLE t; --"]]
    execute_bulk_insert(con, "INSERT INTO t (id, val) VALUES {values}", rows)
    stored = con.execute("SELECT val FROM t WHERE id = 1").fetchone()[0]
    assert stored == "robert'); DROP TABLE t; --"
    # table must still exist
    assert con.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1


def test_works_with_on_conflict_upsert():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val VARCHAR)")
    template = (
        "INSERT INTO t (id, val) VALUES {values} "
        "ON CONFLICT (id) DO UPDATE SET val = excluded.val"
    )

    execute_bulk_insert(con, template, [[1, "first"]])
    execute_bulk_insert(con, template, [[1, "second"]])

    assert con.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    assert con.execute("SELECT val FROM t WHERE id = 1").fetchone()[0] == "second"
    con.close()


def test_preserves_row_order_and_values(con):
    rows = [[3, "c"], [1, "a"], [2, "b"]]
    execute_bulk_insert(con, "INSERT INTO t (id, val) VALUES {values}", rows)
    result = con.execute("SELECT id, val FROM t ORDER BY id").fetchall()
    assert result == [(1, "a"), (2, "b"), (3, "c")]
