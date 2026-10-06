# Runbook: FR Y-14 Governed Agentic Data Product Engine

Operational reference for running, interpreting, and troubleshooting the
engine as built through Phase 7. For architecture rationale and design
detail, see `01-approach-paper.md` / `02-design-document.md`
/ `03-implementation-plan.md`.

## 1. First-time setup

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
python -m fry14_engine.db        # bootstrap data/fry14_engine.duckdb
```

Bootstrapping is idempotent — safe to re-run after a schema change (new
`.sql` files are applied; existing tables are untouched, since every
`CREATE TABLE` is `IF NOT EXISTS`).

## 2. Running the pipeline

### Via the demo CLI (recommended for exploration)

```bash
fry14 demo                                  # defaults: 60 records, 20% bad-record rate
fry14 demo --count 500 --bad-rate 0.3       # bigger, noisier batch
fry14 demo --db-path data/my_run.duckdb     # keep a separate run history
```

This drives the full pipeline through one `Orchestrator.run()` call:
ingest (batch file + event stream) → contract validation (hash PII, route
to governed/quarantine) → risk calculation → aggregation → catalog update
→ one allowed and one denied query-sandbox request. The printed report
includes the `pipeline_run_id` for that run — keep it if you want to dig
into the audit log afterward (§5).

### Via the Orchestrator directly (for integrating into other code)

```python
from fry14_engine.contracts.registry import ContractRegistry
from fry14_engine.db import get_connection
from fry14_engine.ingestion.batch_file_adapter import BatchFileAdapter
from fry14_engine.orchestrator.models import ChannelSource
from fry14_engine.orchestrator.orchestrator import Orchestrator
from fry14_engine.pii.hashing_service import PIIHashingService

connection = get_connection("data/fry14_engine.duckdb")
contract = ContractRegistry("config/contracts").get_active("commercial_loan")
hashing_service = PIIHashingService.from_env()  # requires FRY14_PII_HASH_KEY

channels = [
    ChannelSource(
        adapter=BatchFileAdapter("extract.csv", source_system_of_record="CORE_LOAN_SYSTEM"),
        source_entity_code="ENTITY_001",
        source_system_of_record="CORE_LOAN_SYSTEM",
    ),
]
orchestrator = Orchestrator(connection, contract, hashing_service, data_product_id="commercial_loan.schedule")
report = orchestrator.run(channels, reporting_period="2026-06")
```

`report.pipeline_run_id` ties every downstream table (landing, quarantine,
governed, metrics, aggregates, catalog, audit log) together for this run.

## 3. Interpreting output

| Report section | What it tells you |
|---|---|
| Ingestion | Records landed per channel; parse errors (malformed source rows, not business-rule violations) |
| Contract validation + PII governance | DQ pass rate, quarantine reason-code breakdown — see table below |
| Risk metric calculation | Loans successfully calculated vs. routed to a calculation exception; total EAD/EL/RWA |
| Schedule aggregation | How many aggregate rows (period × segment × grade × maturity bucket) were produced |
| Data product catalog | Health score (70% DQ + 30% SLA, see `catalog/health.py`), SLA status |
| Query sandbox | One allowed, one denied RBAC-gated query, to prove the gate is live |
| Audit trail | Every stage event recorded for this `pipeline_run_id`, in order |

### Exception reason codes

| Code | Stage | Meaning |
|---|---|---|
| `NEGATIVE_BALANCE` | Contract validation | `outstanding_balance < 0` |
| `MISSING_CREDIT_SCORE` | Contract validation | `credit_score` is null |
| `INVALID_CREDIT_GRADE` | Contract validation | `internal_credit_risk_grade` outside 1–10 |
| `NULL_MANDATORY_FIELD` | Contract validation | a non-nullable field (e.g. `asset_class`) is missing |
| `UNKNOWN_ASSET_CLASS` | Contract validation / Risk calc | value not in the contract's allowed set / no reference data for it |
| `MATURITY_BEFORE_ORIGINATION` | Contract validation | cross-field business rule violation |
| `CALC_MISSING_PD_LGD` | Risk calculation | PD or LGD missing — contract allows this field null, so it isn't a quarantine case |
| `CALC_MISSING_MATURITY_DATE` | Risk calculation | can't bucket maturity without a date |

Run `fry14 data-dictionary` for the full field-by-field reference,
generated directly from the active contract (never hand-maintained, so it
can't drift from what's actually enforced).

## 4. Troubleshooting

**"No regulatory parameter set found" / `ReferenceDataNotFoundError`**
The DB wasn't bootstrapped, or `schemas/005_reference_data.sql`'s seed
inserts didn't run. Re-run `python -m fry14_engine.db` against the target
DB file.

**`ContractNotFoundError: No contract versions found for 'commercial_loan'`**
`config/contracts/commercial_loan/` is missing or empty, or you pointed
`ContractRegistry` at the wrong directory. It should contain at least
`1.0.0.yaml`.

**`PermissionDeniedError` from the query sandbox**
Expected behavior for any role without `QUERY_SANDBOX_READ` (see
`rbac/matrix.py` — currently `FINANCE`, `RISK`, `REGULATORY_REPORTING`,
`COMPLIANCE_AUDIT`, `ADMIN`). Not a bug.

**`PIIHashingKeyMissingError`**
`PIIHashingService.from_env()` requires `FRY14_PII_HASH_KEY` to be set.
`fry14 demo` doesn't need this — it uses a documented dev-only default key
(see `demo.py`) so the demo runs with zero setup. Never use that default
outside a demo.

**A run is much slower than expected**
DuckDB's Python `executemany` has very high per-call overhead (a real bug
caught and fixed during Phase 7 — see `common/db_helpers.py`). Every store
in this codebase uses `execute_bulk_insert` (one multi-row `INSERT`
statement) instead. If you add a new store, use the same helper rather
than `executemany` in a loop.

**Pipeline raises after retries ("Gave up after N attempt(s)")**
`Orchestrator` retries each stage up to 3 times (configurable via
`max_retries`) on `duckdb.Error`. If it still fails, the underlying
`last_error` on the raised `RetryExhaustedError` has the real cause —
check for a lock held by another process on the same DuckDB file (DuckDB
only supports one writer at a time).

## 5. Reconstructing a run from the audit log

Every stage of every orchestrated run is recorded to `audit.event_log`,
keyed by `pipeline_run_id`. Given only that id:

```python
from fry14_engine.audit.logger import AuditLogger
from fry14_engine.db import get_connection

connection = get_connection("data/fry14_engine.duckdb")
events = AuditLogger(connection).read_run("<pipeline_run_id>")
for event in events:
    print(event.event_type, event.detail)
```

A complete run produces exactly these event types, in order: `INGESTION`
(once per channel), `VALIDATION`, `PII_HASH`, `CALCULATION`,
`AGGREGATION`, `CATALOG_UPDATE`, `ORCHESTRATION`. Each `detail` payload is
a small summary (counts, versions) — never a raw record or PII value; see
`audit/logger.py`'s own test asserting no PII field name ever appears in
that module's source.

You can also query every downstream table directly by the same id:

```sql
SELECT * FROM landing.raw_loan_record    WHERE pipeline_run_id = '<id>';
SELECT * FROM quarantine.quarantine_record WHERE pipeline_run_id = '<id>';
SELECT * FROM governed.loan_record        WHERE pipeline_run_id = '<id>';
SELECT * FROM metrics.loan_risk_metrics   WHERE pipeline_run_id = '<id>';
SELECT * FROM aggregates.schedule_aggregate WHERE pipeline_run_id = '<id>';
```

Note: `aggregates.schedule_aggregate` upserts by
`(reporting_period, portfolio_segment, credit_rating_grade, remaining_maturity_bucket, schema_version)`,
**not** by `pipeline_run_id` — if you re-run the same reporting period, a
later run's aggregate rows for overlapping group-keys supersede the
earlier run's (by design — the aggregate table is the "current published
view," not a run-by-run history). `metrics.loan_risk_metrics` is
insert-only, so the loan-level detail from every run is preserved even
when its aggregate rollup gets superseded.

## 6. Performance

A reduced-scale smoke test (5,000 synthetic records) runs in CI in a few
seconds end-to-end (ingest → validate → hash → calculate → aggregate →
catalog). The approach paper's target NFR (~100K–1M records within an SLA
window) has not been validated against representative production
infrastructure — that's a deliberate scope boundary of this phase, not an
oversight. If you need that validation, profile first (see
`common/db_helpers.py`'s docstring for the one performance bug already
found and fixed — `executemany` row-by-row inserts) before assuming new
bottlenecks exist.

## 7. What's not built yet

- Re-identification Vault (C8) — schema exists, no code reads/writes it.
- Any HTTP/API layer — every component here is a Python service/gateway,
  not a running server. `catalog`'s "Operational Dashboard" requirement is
  satisfied by the `fry14 demo` CLI report, per the design doc's own
  allowance for "a UI-equivalent report."
- The agentic layer (Phases 8–12): Stress Engine, MCP Tool Server, Policy
  Enforcement Point, the five-agent roster, evaluation harness. Package
  scaffolding exists (`scenario/`, `mcp_server/`, `policy/`,
  `approval_queue/`, `agent_trace/`, `agent_runtime/`, `grounding/`,
  `evaluation/`, `pii_egress/`) but none of it is implemented.
