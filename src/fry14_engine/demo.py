"""End-to-end demo of the engine as built so far: generates synthetic loan
records, ingests them via both the batch-file and event-stream adapters,
validates them against the active `commercial_loan` contract, hashes PII,
routes to the governed or quarantine store, computes EAD/EL/RWA for every
governed record, then aggregates those metrics into schedule-shaped rows.
This exercises exactly the real code paths built in Phases 0-5 — nothing
here is mocked or hardcoded for display purposes.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fry14_engine.aggregation.gateway import AggregationGateway, AggregationRunResult
from fry14_engine.common.enums import IngestionChannel
from fry14_engine.common.ids import new_pipeline_run_id
from fry14_engine.common.metadata import MetadataStamper
from fry14_engine.contracts.registry import ContractRegistry
from fry14_engine.contracts.validation_gateway import ValidationGateway, ValidationRunResult
from fry14_engine.db import REPO_ROOT, bootstrap, get_connection
from fry14_engine.ingestion.batch_file_adapter import BatchFileAdapter
from fry14_engine.ingestion.event_stream_adapter import EventStreamAdapter, InMemoryEventSource
from fry14_engine.ingestion.gateway import IngestionGateway, IngestionRunResult
from fry14_engine.pii.governed_store import GovernedStore
from fry14_engine.pii.hashing_service import PIIHashingService
from fry14_engine.risk_engine.engine import RiskCalculationRunResult
from fry14_engine.risk_engine.gateway import RiskCalculationGateway
from fry14_engine.synthetic.generator import generate_loan_records
from fry14_engine.synthetic.writers import write_csv

DEFAULT_DEMO_DB_PATH = REPO_ROOT / "data" / "demo.duckdb"

# A real deployment injects this via a secrets manager / environment
# variable (see PIIHashingService.from_env) and never hardcodes it. This
# default exists only so `fry14 demo` runs out of the box with no setup.
_DEMO_INSECURE_DEFAULT_HASH_KEY = "dev-only-insecure-default-key-do-not-use-in-production"


@dataclass
class DemoResult:
    db_path: Path
    batch_ingest: IngestionRunResult
    event_ingest: IngestionRunResult
    validation: ValidationRunResult
    risk_calculation: RiskCalculationRunResult
    aggregation: AggregationRunResult
    contract_id: str
    contract_version: str


def run_demo(
    count: int = 60,
    bad_record_rate: float = 0.2,
    seed: int = 42,
    db_path: Path | str = DEFAULT_DEMO_DB_PATH,
    reporting_period: str | None = None,
) -> DemoResult:
    """Run the Phase 0-5 pipeline once and return a structured result.

    Splits `count` records 75/25 between the batch-file channel and the
    event-stream channel, so both ingestion adapters are genuinely
    exercised, validates the combined set against the active
    `commercial_loan` contract (hashing PII and routing to the governed or
    quarantine store), computes EAD/EL/RWA for every governed record as of
    `reporting_period` (defaults to the current month), then aggregates
    those metrics into schedule-shaped rows.
    """
    db_path = Path(db_path)
    reporting_period = reporting_period or datetime.now(UTC).strftime("%Y-%m")
    bootstrap(db_path)
    connection = get_connection(db_path)

    batch_count = int(count * 0.75)
    event_count = count - batch_count

    batch_raw = generate_loan_records(count=batch_count, bad_record_rate=bad_record_rate, seed=seed)
    event_raw = generate_loan_records(
        count=event_count,
        bad_record_rate=bad_record_rate,
        seed=seed + 1,
        start_index=batch_count,  # non-overlapping loan_ids vs. the batch channel
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        csv_path = Path(tmp_dir) / "loan_extract.csv"
        write_csv(batch_raw, csv_path)

        batch_run_id = new_pipeline_run_id()
        batch_adapter = BatchFileAdapter(csv_path, source_system_of_record="CORE_LOAN_SYSTEM")
        batch_stamper = MetadataStamper(
            pipeline_run_id=batch_run_id,
            source_entity_code="ENTITY_001",
            source_system_of_record="CORE_LOAN_SYSTEM",
            ingestion_channel=IngestionChannel.BATCH,
        )
        ingestion_gateway = IngestionGateway(connection)
        batch_ingest = ingestion_gateway.run(batch_adapter, batch_stamper)

        event_source = InMemoryEventSource()
        for record in event_raw:
            event_source.publish(record)
        event_run_id = new_pipeline_run_id()
        event_adapter = EventStreamAdapter(
            event_source, source_system_of_record="CREDIT_PERFORMANCE_FEED"
        )
        event_stamper = MetadataStamper(
            pipeline_run_id=event_run_id,
            source_entity_code="ENTITY_001",
            source_system_of_record="CREDIT_PERFORMANCE_FEED",
            ingestion_channel=IngestionChannel.EVENT,
        )
        event_ingest = ingestion_gateway.run(event_adapter, event_stamper)

    registry = ContractRegistry(REPO_ROOT / "config" / "contracts", connection=connection)
    contract = registry.get_active("commercial_loan")

    stamped_records = batch_ingest.stamped_records + event_ingest.stamped_records
    validation_run_id = new_pipeline_run_id()
    pii_hashing_service = PIIHashingService(_DEMO_INSECURE_DEFAULT_HASH_KEY)
    validation_gateway = ValidationGateway(connection, pii_hashing_service)
    validation = validation_gateway.run(stamped_records, contract, validation_run_id)

    governed_records = GovernedStore(connection).read_by_pipeline_run_id(validation_run_id)
    risk_run_id = new_pipeline_run_id()
    risk_calculation_gateway = RiskCalculationGateway(connection)
    risk_calculation = risk_calculation_gateway.run(governed_records, reporting_period, risk_run_id)

    aggregation_gateway = AggregationGateway(connection)
    aggregation = aggregation_gateway.run(risk_run_id)

    connection.close()

    return DemoResult(
        db_path=db_path,
        batch_ingest=batch_ingest,
        event_ingest=event_ingest,
        validation=validation,
        risk_calculation=risk_calculation,
        aggregation=aggregation,
        contract_id=contract.contract_id,
        contract_version=contract.version,
    )


def format_report(result: DemoResult) -> str:
    lines: list[str] = []
    w = lines.append

    w("=" * 64)
    w("FR Y-14 ENGINE DEMO - Phases 0-5 (ingestion through aggregation)")
    w("=" * 64)
    w("")
    w(f"Database: {result.db_path}")
    w("")
    w("-- Ingestion " + "-" * 51)
    w(
        f"  Batch file adapter   : {result.batch_ingest.records_landed:>4} records landed"
        f"  (run {result.batch_ingest.pipeline_run_id[:8]}..., "
        f"{len(result.batch_ingest.parse_errors)} parse errors)"
    )
    w(
        f"  Event stream adapter : {result.event_ingest.records_landed:>4} records landed"
        f"  (run {result.event_ingest.pipeline_run_id[:8]}..., "
        f"{len(result.event_ingest.parse_errors)} parse errors)"
    )
    w("")
    w("-- Contract validation + PII governance " + "-" * 23)
    w(f"  Contract: {result.contract_id} v{result.contract_version}")
    w(f"  Total records     : {result.validation.total_count}")
    w(f"  Governed (hashed) : {result.validation.governed_count}")
    w(f"  Quarantined       : {result.validation.quarantined_count}")
    w(f"  DQ pass rate      : {result.validation.dq_pass_rate:.1%}")
    w("")
    if result.validation.reason_code_counts:
        w("  Quarantine reason codes:")
        for code, n in sorted(result.validation.reason_code_counts.items(), key=lambda kv: -kv[1]):
            w(f"    {code:<28} {n:>4}")
    else:
        w("  No quarantined records.")
    w("")
    w("-- Risk metric calculation " + "-" * 37)
    rc = result.risk_calculation
    w(f"  Reporting period        : {rc.reporting_period}")
    w(f"  Regulatory parameters   : v{rc.regulatory_parameter_version}")
    w(f"  Loans calculated        : {len(rc.metrics)}")
    w(f"  Calculation exceptions  : {len(rc.exceptions)}")
    if rc.metrics:
        total_ead = sum((m.ead for m in rc.metrics), Decimal("0"))
        total_el = sum((m.el for m in rc.metrics), Decimal("0"))
        total_rwa = sum((m.rwa for m in rc.metrics), Decimal("0"))
        w(f"  Total EAD               : {total_ead:>18,.2f}")
        w(f"  Total EL                : {total_el:>18,.2f}")
        w(f"  Total RWA               : {total_rwa:>18,.2f}")
    if rc.exceptions:
        w("  Calculation exception reason codes:")
        counts: dict[str, int] = {}
        for exc in rc.exceptions:
            counts[exc.reason_code] = counts.get(exc.reason_code, 0) + 1
        for code, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            w(f"    {code:<28} {n:>4}")
    w("")
    w("-- Schedule aggregation " + "-" * 41)
    agg = result.aggregation
    w(f"  Schema version           : v{agg.schema_version}")
    w(f"  Input metric rows        : {agg.input_metric_count}")
    w(f"  Aggregate rows produced  : {len(agg.aggregates)}")
    if agg.aggregates:
        w("  By portfolio segment x grade x maturity bucket:")
        for row in sorted(
            agg.aggregates, key=lambda r: (r.portfolio_segment, r.credit_rating_grade)
        ):
            w(
                f"    {row.portfolio_segment:<16} grade={row.credit_rating_grade:>2} "
                f"{str(row.remaining_maturity_bucket):<8} loans={row.loan_count:>3} "
                f"EAD={row.total_ead:>15,.2f}"
            )
    w("")
    w("=" * 64)
    w(
        "Note: aggregate rows are persisted to aggregates.schedule_aggregate,"
        " upserted (idempotent re-aggregation). Phase 6+ (catalog, query"
        " sandbox) isn't built yet, so there's no consumer-facing view of them."
    )
    return "\n".join(lines)
