"""End-to-end demo of the engine as built so far: a single `Orchestrator.run()`
call sequences synthetic loan ingestion (batch file + event stream),
contract validation, PII hashing, risk calculation, aggregation, and
catalog update under one `pipeline_run_id` — then demonstrates the
RBAC-scoped query sandbox (one allowed query, one denied) and reconstructs
the full run from the audit log. This exercises exactly the real code
paths built in Phases 0-7 — nothing here is mocked or hardcoded for
display purposes.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fry14_engine.audit.logger import AuditLogger
from fry14_engine.audit.models import AuditEvent
from fry14_engine.catalog.query_sandbox import QuerySandboxService
from fry14_engine.common.enums import RoleName
from fry14_engine.contracts.registry import ContractRegistry
from fry14_engine.db import REPO_ROOT, bootstrap, get_connection
from fry14_engine.ingestion.batch_file_adapter import BatchFileAdapter
from fry14_engine.ingestion.event_stream_adapter import EventStreamAdapter, InMemoryEventSource
from fry14_engine.orchestrator.models import ChannelSource, PipelineRunReport
from fry14_engine.orchestrator.orchestrator import Orchestrator
from fry14_engine.pii.hashing_service import PIIHashingService
from fry14_engine.rbac.service import PermissionDeniedError
from fry14_engine.synthetic.generator import generate_loan_records
from fry14_engine.synthetic.writers import write_csv

DEFAULT_DEMO_DB_PATH = REPO_ROOT / "data" / "demo.duckdb"

# A real deployment injects this via a secrets manager / environment
# variable (see PIIHashingService.from_env) and never hardcodes it. This
# default exists only so `fry14 demo` runs out of the box with no setup.
_DEMO_INSECURE_DEFAULT_HASH_KEY = "dev-only-insecure-default-key-do-not-use-in-production"


@dataclass
class SandboxDemo:
    allowed_role: RoleName
    allowed_row_count: int
    denied_role: RoleName
    denied_as_expected: bool


@dataclass
class DemoResult:
    db_path: Path
    report: PipelineRunReport
    sandbox: SandboxDemo
    audit_events: list[AuditEvent]
    contract_id: str
    contract_version: str


def run_demo(
    count: int = 60,
    bad_record_rate: float = 0.2,
    seed: int = 42,
    db_path: Path | str = DEFAULT_DEMO_DB_PATH,
    reporting_period: str | None = None,
) -> DemoResult:
    """Run the Phase 0-7 pipeline once, via the real `Orchestrator`, and
    return a structured result.

    Splits `count` records 75/25 between the batch-file channel and the
    event-stream channel — both feed the *same* `pipeline_run_id`, so the
    whole run (landing, quarantine, governed, metrics, aggregates, catalog,
    audit log) is traceable from that one id.
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

    registry = ContractRegistry(REPO_ROOT / "config" / "contracts", connection=connection)
    contract = registry.get_active("commercial_loan")

    pii_hashing_service = PIIHashingService(_DEMO_INSECURE_DEFAULT_HASH_KEY)
    data_product_id = f"{contract.contract_id}.schedule"
    orchestrator = Orchestrator(connection, contract, pii_hashing_service, data_product_id)

    with tempfile.TemporaryDirectory() as tmp_dir:
        csv_path = Path(tmp_dir) / "loan_extract.csv"
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
        report = orchestrator.run(channels, reporting_period)

    sandbox_service = QuerySandboxService(connection)
    allowed_rows = sandbox_service.query_schedule(
        RoleName.FINANCE, reporting_period, report.aggregation.schema_version
    )
    denied_as_expected = False
    try:
        sandbox_service.query_schedule(
            RoleName.DATA_ENGINEER, reporting_period, report.aggregation.schema_version
        )
    except PermissionDeniedError:
        denied_as_expected = True
    sandbox = SandboxDemo(
        allowed_role=RoleName.FINANCE,
        allowed_row_count=len(allowed_rows),
        denied_role=RoleName.DATA_ENGINEER,
        denied_as_expected=denied_as_expected,
    )

    audit_events = AuditLogger(connection).read_run(report.pipeline_run_id)

    connection.close()

    return DemoResult(
        db_path=db_path,
        report=report,
        sandbox=sandbox,
        audit_events=audit_events,
        contract_id=contract.contract_id,
        contract_version=contract.version,
    )


def format_report(result: DemoResult) -> str:
    lines: list[str] = []
    w = lines.append
    report = result.report

    w("=" * 64)
    w("FR Y-14 ENGINE DEMO - Phases 0-7 (full pipeline via Orchestrator)")
    w("=" * 64)
    w("")
    w(f"Database: {result.db_path}")
    w(f"Pipeline run id: {report.pipeline_run_id}")
    w("")
    w("-- Ingestion " + "-" * 51)
    for ingestion in report.ingestion_results:
        w(
            f"  {ingestion.records_landed:>4} records landed, "
            f"{len(ingestion.parse_errors)} parse errors"
        )
    w("")
    w("-- Contract validation + PII governance " + "-" * 23)
    validation = report.validation
    w(f"  Contract: {result.contract_id} v{result.contract_version}")
    w(f"  Total records     : {validation.total_count}")
    w(f"  Governed (hashed) : {validation.governed_count}")
    w(f"  Quarantined       : {validation.quarantined_count}")
    w(f"  DQ pass rate      : {validation.dq_pass_rate:.1%}")
    w("")
    if validation.reason_code_counts:
        w("  Quarantine reason codes:")
        for code, n in sorted(validation.reason_code_counts.items(), key=lambda kv: -kv[1]):
            w(f"    {code:<28} {n:>4}")
    else:
        w("  No quarantined records.")
    w("")
    w("-- Risk metric calculation " + "-" * 37)
    rc = report.risk_calculation
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
    w("")
    w("-- Schedule aggregation " + "-" * 41)
    agg = report.aggregation
    w(f"  Schema version           : v{agg.schema_version}")
    w(f"  Input metric rows        : {agg.input_metric_count}")
    w(f"  Aggregate rows produced  : {len(agg.aggregates)}")
    w("")
    w("-- Data product catalog " + "-" * 41)
    entry = report.catalog.entry
    w(f"  Data product             : {entry.data_product_id}")
    w(f"  Health score              : {entry.health_score}")
    w(f"  DQ pass %                 : {entry.dq_pass_percentage}")
    w(f"  SLA status                 : {entry.sla_status}")
    w("")
    w("-- Query sandbox (RBAC-scoped, read-only) " + "-" * 22)
    sb = result.sandbox
    w(f"  {sb.allowed_role} query  : ALLOWED, {sb.allowed_row_count} rows returned")
    w(
        f"  {sb.denied_role} query  : "
        f"{'DENIED as expected' if sb.denied_as_expected else 'UNEXPECTEDLY ALLOWED'}"
    )
    w("")
    w("-- Audit trail (reconstructed from pipeline_run_id) " + "-" * 12)
    w(f"  Events recorded: {len(result.audit_events)}")
    for event in result.audit_events:
        w(f"    {event.event_type}")
    w("")
    w("=" * 64)
    w(
        "Note: the entire run above was sequenced by one Orchestrator.run() call"
        " under a single pipeline_run_id - every stage's output, and the audit"
        " trail reconstructing it, trace back to that one id."
    )
    return "\n".join(lines)
