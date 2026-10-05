from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fry14_engine.catalog.gateway import CatalogGateway
from fry14_engine.common.enums import SlaStatus
from fry14_engine.db import bootstrap, get_connection


def test_update_after_run_creates_entry_and_history(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    gateway = CatalogGateway(con)

    result = gateway.update_after_run(
        data_product_id="commercial_loan.schedule",
        pipeline_run_id="run-1",
        dq_pass_percentage=92.5,
        run_completed_at=datetime.now(UTC) - timedelta(hours=1),
        output_schema_version="1.0.0",
        output_schema_effective_date=date(2026, 6, 1),
    )

    assert result.entry.data_product_id == "commercial_loan.schedule"
    assert result.entry.dq_pass_percentage == 92.5
    assert result.entry.sla_status == SlaStatus.ON_TIME
    assert result.entry.last_run_id == "run-1"

    stored = gateway.get_entry("commercial_loan.schedule")
    assert stored is not None
    assert stored.health_score == result.entry.health_score

    history = gateway.get_schema_version_history("commercial_loan.schedule")
    assert len(history) == 1
    assert history[0].version == "1.0.0"
    con.close()


def test_rerun_upserts_entry_not_duplicates(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    gateway = CatalogGateway(con)

    gateway.update_after_run(
        data_product_id="commercial_loan.schedule",
        pipeline_run_id="run-1",
        dq_pass_percentage=80.0,
        run_completed_at=datetime.now(UTC),
        output_schema_version="1.0.0",
        output_schema_effective_date=date(2026, 6, 1),
    )
    gateway.update_after_run(
        data_product_id="commercial_loan.schedule",
        pipeline_run_id="run-2",
        dq_pass_percentage=95.0,
        run_completed_at=datetime.now(UTC),
        output_schema_version="1.0.0",
        output_schema_effective_date=date(2026, 6, 1),
    )

    row_count = con.execute(
        "SELECT COUNT(*) FROM catalog.data_product_catalog_entry "
        "WHERE data_product_id = 'commercial_loan.schedule'"
    ).fetchone()[0]
    assert row_count == 1  # upserted, not duplicated

    entry = gateway.get_entry("commercial_loan.schedule")
    assert entry.dq_pass_percentage == 95.0  # reflects the latest run
    assert entry.last_run_id == "run-2"
    con.close()


def test_schema_version_history_is_append_only_and_deduplicated(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    gateway = CatalogGateway(con)

    for _ in range(3):
        gateway.update_after_run(
            data_product_id="commercial_loan.schedule",
            pipeline_run_id="run-1",
            dq_pass_percentage=90.0,
            run_completed_at=datetime.now(UTC),
            output_schema_version="1.0.0",  # same version every time
            output_schema_effective_date=date(2026, 6, 1),
        )

    history = gateway.get_schema_version_history("commercial_loan.schedule")
    assert len(history) == 1  # recorded once, not three times

    gateway.update_after_run(
        data_product_id="commercial_loan.schedule",
        pipeline_run_id="run-2",
        dq_pass_percentage=90.0,
        run_completed_at=datetime.now(UTC),
        output_schema_version="2.0.0",  # a genuinely new version
        output_schema_effective_date=date(2026, 7, 1),
    )

    history = gateway.get_schema_version_history("commercial_loan.schedule")
    assert {h.version for h in history} == {"1.0.0", "2.0.0"}
    con.close()


def test_sla_status_breached_for_stale_run(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    gateway = CatalogGateway(con)

    result = gateway.update_after_run(
        data_product_id="commercial_loan.schedule",
        pipeline_run_id="run-1",
        dq_pass_percentage=100.0,
        run_completed_at=datetime.now(UTC) - timedelta(days=10),
        output_schema_version="1.0.0",
        output_schema_effective_date=date(2026, 6, 1),
    )

    assert result.entry.sla_status == SlaStatus.BREACHED
    # 100% DQ but breached SLA still caps health score well below 100
    assert result.entry.health_score < 100
    con.close()


def test_get_entry_returns_none_when_not_found(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    gateway = CatalogGateway(con)

    assert gateway.get_entry("nonexistent.product") is None
    assert gateway.get_schema_version_history("nonexistent.product") == []
    con.close()
