"""Database bootstrap: applies the DDL files under schemas/ to a DuckDB
database file, in filename order, so every logical zone (landing, quarantine,
governed, metrics, aggregates, catalog, reference, rbac, audit, contracts,
scenario, agent_governance) exists before any component runs. See
02-design-document.md §8.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = REPO_ROOT / "schemas"
DEFAULT_DB_PATH = REPO_ROOT / "data" / "fry14_engine.duckdb"


def _schema_files() -> list[Path]:
    return sorted(SCHEMAS_DIR.glob("*.sql"))


def bootstrap(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    """Create (or update) all schemas/tables in the target DuckDB file."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        for schema_file in _schema_files():
            con.execute(schema_file.read_text(encoding="utf-8"))
    finally:
        con.close()


def get_connection(db_path: Path | str = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    """Open a connection to the engine's DuckDB store, bootstrapping it first
    if it does not already exist."""
    db_path = Path(db_path)
    if not db_path.exists():
        bootstrap(db_path)
    return duckdb.connect(str(db_path))


if __name__ == "__main__":
    bootstrap()
    print(f"Bootstrapped database at {DEFAULT_DB_PATH}")
