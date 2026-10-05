from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fry14_engine.db import bootstrap, get_connection
from fry14_engine.reference_data.store import ReferenceDataStore


def test_seeded_parameter_set_loads_correctly(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    store = ReferenceDataStore(con)

    assert store.list_versions() == ["1.0.0"]

    parameter_set = store.get_active()
    assert parameter_set.version == "1.0.0"
    assert parameter_set.get_ccf("CRE", "STANDARD") == Decimal("0.5")
    assert parameter_set.get_ccf("C&I", "STANDARD") == Decimal("0.2")
    assert parameter_set.get_risk_weight("CRE") == Decimal("1.00")
    assert parameter_set.get_risk_weight("C&I") == Decimal("1.00")
    con.close()


def test_bootstrap_seeding_is_idempotent(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    bootstrap(tmp_db_path)  # re-run must not duplicate seed rows
    con = get_connection(tmp_db_path)

    version_count = con.execute(
        "SELECT COUNT(*) FROM reference.regulatory_parameter_set WHERE version = '1.0.0'"
    ).fetchone()[0]
    ccf_count = con.execute("SELECT COUNT(*) FROM reference.credit_conversion_factor").fetchone()[0]

    assert version_count == 1
    assert ccf_count == 2
    con.close()
