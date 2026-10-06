"""Performance smoke test (Phase 7).

The approach paper's NFR target is ~100K-1M synthetic records processed
within a defined SLA window on demo-scale infra. Running the full 100K
figure in CI would be slow and isn't representative of real deployment
hardware anyway, so this test exercises a reduced scale (5,000 records)
with a generous time budget, as a smoke check that nothing in the pipeline
is accidentally quadratic or otherwise pathological — not a validated
measurement of the 100K NFR itself. A true capacity test against that
target belongs on representative infrastructure, not this suite.
"""

from __future__ import annotations

import time
from pathlib import Path

from fry14_engine.contracts.registry import ContractRegistry
from fry14_engine.db import bootstrap, get_connection
from fry14_engine.ingestion.batch_file_adapter import BatchFileAdapter
from fry14_engine.orchestrator.models import ChannelSource
from fry14_engine.orchestrator.orchestrator import Orchestrator
from fry14_engine.pii.hashing_service import PIIHashingService
from fry14_engine.synthetic.generator import generate_loan_records
from fry14_engine.synthetic.writers import write_csv

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_TEST_RECORD_COUNT = 5_000
SMOKE_TEST_TIME_BUDGET_SECONDS = 60.0


def test_pipeline_handles_five_thousand_records_within_time_budget(
    tmp_db_path: Path, tmp_path: Path
):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    registry = ContractRegistry(REPO_ROOT / "config" / "contracts")
    contract = registry.get_active("commercial_loan")

    raw = generate_loan_records(count=SMOKE_TEST_RECORD_COUNT, bad_record_rate=0.1, seed=7001)
    csv_path = tmp_path / "perf_extract.csv"
    write_csv(raw, csv_path)

    channels = [
        ChannelSource(
            adapter=BatchFileAdapter(csv_path, source_system_of_record="CORE_LOAN_SYSTEM"),
            source_entity_code="ENTITY_001",
            source_system_of_record="CORE_LOAN_SYSTEM",
        )
    ]
    orchestrator = Orchestrator(
        con,
        contract,
        PIIHashingService("perf-smoke-test-key"),
        data_product_id="commercial_loan.schedule",
    )

    started = time.monotonic()
    report = orchestrator.run(channels, reporting_period="2026-06")
    elapsed = time.monotonic() - started

    assert report.validation.total_count == SMOKE_TEST_RECORD_COUNT
    budget_message = (
        f"Pipeline took {elapsed:.1f}s for {SMOKE_TEST_RECORD_COUNT} records "
        f"(budget {SMOKE_TEST_TIME_BUDGET_SECONDS}s)"
    )
    assert elapsed < SMOKE_TEST_TIME_BUDGET_SECONDS, budget_message

    throughput = SMOKE_TEST_RECORD_COUNT / elapsed
    print(
        f"\nPerformance smoke test: {SMOKE_TEST_RECORD_COUNT} records in {elapsed:.2f}s "
        f"({throughput:.0f} records/sec)"
    )
    con.close()
