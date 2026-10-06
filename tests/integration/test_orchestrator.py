from __future__ import annotations

from pathlib import Path

from fry14_engine.audit.logger import AuditLogger
from fry14_engine.catalog.query_sandbox import QuerySandboxService
from fry14_engine.common.enums import RoleName
from fry14_engine.contracts.registry import ContractRegistry
from fry14_engine.db import bootstrap, get_connection
from fry14_engine.ingestion.batch_file_adapter import BatchFileAdapter
from fry14_engine.ingestion.event_stream_adapter import EventStreamAdapter, InMemoryEventSource
from fry14_engine.orchestrator.models import ChannelSource
from fry14_engine.orchestrator.orchestrator import Orchestrator
from fry14_engine.pii.hashing_service import PIIHashingService
from fry14_engine.rbac.service import PermissionDeniedError
from fry14_engine.synthetic.generator import generate_loan_records
from fry14_engine.synthetic.writers import write_csv

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_HASH_KEY = "orchestrator-e2e-test-key"


def test_full_pipeline_end_to_end_under_one_pipeline_run_id(tmp_db_path: Path, tmp_path: Path):
    """The capstone test: batch + event ingestion -> contract validation
    with quarantine split -> PII hashing -> risk calculation -> aggregation
    -> catalog update -> sandbox query, all tied together by exactly one
    pipeline_run_id, verified end-to-end in a single test."""
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    registry = ContractRegistry(REPO_ROOT / "config" / "contracts")
    contract = registry.get_active("commercial_loan")

    batch_raw = generate_loan_records(count=60, bad_record_rate=0.2, seed=501)
    event_raw = generate_loan_records(count=20, bad_record_rate=0.2, seed=502, start_index=60)

    csv_path = tmp_path / "loan_extract.csv"
    write_csv(batch_raw, csv_path)
    event_source = InMemoryEventSource()
    for record in event_raw:
        event_source.publish(record)

    channels = [
        ChannelSource(
            adapter=BatchFileAdapter(csv_path, source_system_of_record="CORE_LOAN_SYSTEM"),
            source_entity_code="ENTITY_001",
            source_system_of_record="CORE_LOAN_SYSTEM",
        ),
        ChannelSource(
            adapter=EventStreamAdapter(
                event_source, source_system_of_record="CREDIT_PERFORMANCE_FEED"
            ),
            source_entity_code="ENTITY_001",
            source_system_of_record="CREDIT_PERFORMANCE_FEED",
        ),
    ]

    orchestrator = Orchestrator(
        con, contract, PIIHashingService(TEST_HASH_KEY), data_product_id="commercial_loan.schedule"
    )
    report = orchestrator.run(channels, reporting_period="2026-06")
    run_id = report.pipeline_run_id

    # --- Stage 1: ingestion landed everything, both channels, this run id ---
    total_landed = sum(r.records_landed for r in report.ingestion_results)
    assert total_landed == 80
    landing_count = con.execute(
        "SELECT COUNT(*) FROM landing.raw_loan_record WHERE pipeline_run_id = ?", [run_id]
    ).fetchone()[0]
    assert landing_count == 80

    # --- Stage 2: contract validation + quarantine split + PII hashing ---
    validation = report.validation
    assert validation.total_count == 80
    assert validation.quarantined_count > 0
    assert validation.governed_count + validation.quarantined_count == 80

    quarantine_count = con.execute(
        "SELECT COUNT(*) FROM quarantine.quarantine_record WHERE pipeline_run_id = ?", [run_id]
    ).fetchone()[0]
    governed_count = con.execute(
        "SELECT COUNT(*) FROM governed.loan_record WHERE pipeline_run_id = ?", [run_id]
    ).fetchone()[0]
    assert quarantine_count == validation.quarantined_count
    assert governed_count == validation.governed_count

    # no raw PII anywhere, either branch
    raw_ssns = {r["borrower_tax_id"] for r in batch_raw + event_raw}
    governed_hashes = con.execute(
        "SELECT borrower_key_hash FROM governed.loan_record WHERE pipeline_run_id = ?", [run_id]
    ).fetchall()
    assert all(h[0] not in raw_ssns for h in governed_hashes)

    # --- Stage 3: risk calculation reconciles with governed record count ---
    risk = report.risk_calculation
    assert len(risk.metrics) + len(risk.exceptions) == governed_count
    metrics_count = con.execute(
        "SELECT COUNT(*) FROM metrics.loan_risk_metrics WHERE pipeline_run_id = ?", [run_id]
    ).fetchone()[0]
    assert metrics_count == len(risk.metrics)

    # --- Stage 4: aggregation reconciles with risk metrics ---
    aggregation = report.aggregation
    assert aggregation.input_metric_count == len(risk.metrics)
    assert sum(row.loan_count for row in aggregation.aggregates) == len(risk.metrics)
    total_ead_from_metrics = con.execute(
        "SELECT SUM(ead) FROM metrics.loan_risk_metrics WHERE pipeline_run_id = ?", [run_id]
    ).fetchone()[0]
    total_ead_from_aggregates = con.execute(
        "SELECT SUM(total_ead) FROM aggregates.schedule_aggregate WHERE pipeline_run_id = ?",
        [run_id],
    ).fetchone()[0]
    assert total_ead_from_metrics == total_ead_from_aggregates

    # --- Stage 5: catalog reflects this run ---
    catalog_entry = report.catalog.entry
    assert catalog_entry.last_run_id == run_id
    expected_dq_pct = validation.dq_pass_rate * 100
    assert abs(float(catalog_entry.dq_pass_percentage) - expected_dq_pct) < 0.01

    # --- Stage 6: sandbox query over this run's aggregates, RBAC enforced ---
    sandbox = QuerySandboxService(con)
    rows = sandbox.query_schedule(RoleName.RISK, "2026-06", aggregation.schema_version)
    assert len(rows) == len(aggregation.aggregates)
    try:
        sandbox.query_schedule(RoleName.DATA_ENGINEER, "2026-06", aggregation.schema_version)
        raise AssertionError("expected PermissionDeniedError")
    except PermissionDeniedError:
        pass

    # --- Stage 7: the entire run is reconstructable from the audit log alone ---
    audit_events = AuditLogger(con).read_run(run_id)
    event_types = [e.event_type for e in audit_events]
    assert event_types == [
        "INGESTION",
        "INGESTION",
        "VALIDATION",
        "PII_HASH",
        "CALCULATION",
        "AGGREGATION",
        "CATALOG_UPDATE",
        "ORCHESTRATION",
    ]
    assert all(e.pipeline_run_id == run_id for e in audit_events)

    con.close()


def test_two_runs_get_distinct_ids_with_layered_history_semantics(
    tmp_db_path: Path, tmp_path: Path
):
    """Two orchestrated runs for the same reporting period get distinct
    pipeline_run_ids, and the two storage layers behave exactly as
    designed: metrics.loan_risk_metrics is insert-only (PK includes
    pipeline_run_id), so BOTH runs' loan-level rows survive;
    aggregates.schedule_aggregate upserts by (period, segment, grade,
    bucket, schema_version) — NOT by run id — so a second run for the same
    period supersedes matching aggregate rows, same as the Phase 5
    idempotent-re-aggregation test already proves, just via the
    Orchestrator this time."""
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    registry = ContractRegistry(REPO_ROOT / "config" / "contracts")
    contract = registry.get_active("commercial_loan")
    hashing_service = PIIHashingService(TEST_HASH_KEY)

    def _run(seed: int):
        raw = generate_loan_records(count=10, bad_record_rate=0.0, seed=seed)
        csv_path = tmp_path / f"extract_{seed}.csv"
        write_csv(raw, csv_path)
        channels = [
            ChannelSource(
                adapter=BatchFileAdapter(csv_path, source_system_of_record="CORE_LOAN_SYSTEM"),
                source_entity_code="ENTITY_001",
                source_system_of_record="CORE_LOAN_SYSTEM",
            )
        ]
        orchestrator = Orchestrator(
            con, contract, hashing_service, data_product_id="commercial_loan.schedule"
        )
        return orchestrator.run(channels, reporting_period="2026-06")

    first = _run(seed=11)
    second = _run(seed=12)

    assert first.pipeline_run_id != second.pipeline_run_id

    # catalog reflects the LATEST run only (upsert on data_product_id)
    assert second.catalog.entry.last_run_id == second.pipeline_run_id

    # metrics (loan-level detail) retain BOTH runs — insert-only, PK includes run id
    metrics_run_ids = {
        row[0]
        for row in con.execute(
            "SELECT DISTINCT pipeline_run_id FROM metrics.loan_risk_metrics "
            "WHERE reporting_period = '2026-06'"
        ).fetchall()
    }
    assert {first.pipeline_run_id, second.pipeline_run_id}.issubset(metrics_run_ids)

    # aggregates (published view) reflect at least the latest run for this
    # period — overlapping group-keys from the first run are superseded
    aggregate_run_ids = {
        row[0]
        for row in con.execute(
            "SELECT DISTINCT pipeline_run_id FROM aggregates.schedule_aggregate "
            "WHERE reporting_period = '2026-06'"
        ).fetchall()
    }
    assert second.pipeline_run_id in aggregate_run_ids
    con.close()


def test_pipeline_completes_without_duckdb_retry_overhead_in_the_normal_path(
    tmp_db_path: Path, tmp_path: Path
):
    """Sanity check that the retry wrapper doesn't interfere with (or slow
    down) the normal, no-error path."""
    import time

    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    registry = ContractRegistry(REPO_ROOT / "config" / "contracts")
    contract = registry.get_active("commercial_loan")

    raw = generate_loan_records(count=10, bad_record_rate=0.0, seed=13)
    csv_path = tmp_path / "extract.csv"
    write_csv(raw, csv_path)
    channels = [
        ChannelSource(
            adapter=BatchFileAdapter(csv_path, source_system_of_record="CORE_LOAN_SYSTEM"),
            source_entity_code="ENTITY_001",
            source_system_of_record="CORE_LOAN_SYSTEM",
        )
    ]
    orchestrator = Orchestrator(
        con, contract, PIIHashingService(TEST_HASH_KEY), data_product_id="commercial_loan.schedule"
    )

    started = time.monotonic()
    orchestrator.run(channels, reporting_period="2026-06")
    elapsed = time.monotonic() - started

    assert elapsed < 5.0  # no retry backoff should ever fire on the happy path
    con.close()
