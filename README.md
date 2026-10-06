# Governed Agentic Data Product Orchestrator & Stress Scenario Agent (FR Y-14 / CCAR)

**v2.0 (agentic)** · supersedes the v1.0 deterministic-only design (see
[`docs/legacy-v1/`](docs/legacy-v1/)).

Synthetic-data reference implementation of a governed regulatory reporting
pipeline — ingestion → contract validation/quarantine → PII hashing →
credit risk metrics (EAD/EL/RWA) → schedule aggregation → data product
catalog + read-only query sandbox — with a **governed agentic layer** on
top: five AI agents operate the pipeline, triage data quality exceptions,
translate natural-language stress requests into structured scenarios, and
write executive summaries. Every number is still produced by deterministic,
versioned, testable code; agents plan, call tools, interpret, and explain,
never calculate.

See the design docs for full context:

- [`requirements.md`](requirements.md) — source functional requirements
- [`01-approach-paper.md`](01-approach-paper.md) — architecture rationale, principles, trade-offs
- [`02-design-document.md`](02-design-document.md) — component/data/interface design
- [`03-implementation-plan.md`](03-implementation-plan.md) — phased delivery plan
- [`RUNBOOK.md`](RUNBOOK.md) — how to run it, interpret output, troubleshoot, and reconstruct a run from its audit log

## Agentic layer roster

| Agent | Role | Guardrail |
|---|---|---|
| AG-1 Pipeline Operations | Supervisor over orchestrator tools | Plan shown before execution; pauses/escalates instead of publishing on threshold breach |
| AG-2 Data Quality Triage | Clusters quarantine exceptions, infers root cause | Output is proposals only, never auto-applied |
| AG-3 Stress Scenario | NL request → typed `ScenarioSpec` → confirmation → deterministic run | Ad-hoc shocks auto-labeled EXPLORATORY |
| AG-4 Executive Reporting | Grounded narratives for runs/scenarios | Numeric Grounding Checker blocks unbound numbers |
| AG-5 Data Product Concierge | NL question → guarded read-only SQL | SQL parsed/allow-listed; runs under the user's own RBAC permissions |

All five agents reach the engine only through the MCP Tool Server (C23), gated by a deterministic
Policy Enforcement Point (C24) that assigns AUTONOMOUS / CONFIRM / PROPOSE / HUMAN_ONLY / PROHIBITED
per tool call. See `02-design-document.md` §1 (C17–C31) and §2.10–2.12.

## Project layout

```
src/fry14_engine/
  common/          ids.py, enums.py, metadata.py — shared utilities (Phase 0)
    db_helpers.py          execute_bulk_insert: one multi-row INSERT, not row-at-a-time executemany
                           (a real ~100x perf bug found and fixed in Phase 7 — see RUNBOOK.md §6)
  ingestion/        batch + event adapters, landing store, gateway (Phase 1 — done)
    adapter.py           IngestionAdapter ABC + IngestionBatch
    models.py            RawLoanRecord (type-coercing, permissive)
    batch_file_adapter.py  CSV / JSON / JSON-Lines file ingestion
    event_stream_adapter.py  simulated event-driven ingestion (in-memory or file-append-log)
    landing_store.py      append-only writer into landing.raw_loan_record
    gateway.py             orchestrates one adapter's read -> stamp -> land cycle
  synthetic/        synthetic loan record generator + CSV/JSONL file writers (Phase 1 — done)
  contracts/        contract registry, validation engine, business rules, gateway (Phase 2 — done)
    models.py            DataContract, FieldContract, BusinessRule (pydantic)
    business_rules.py     rule_id -> predicate registry (expressions are doc-only, never eval'd)
    registry.py            loads versioned YAML contracts; mirrors into contracts.* tables
    validation_engine.py    per-record check -> every applicable reason code, not just the first
    validation_gateway.py    hashes PII (regardless of pass/fail), then routes: valid -> governed, invalid -> quarantine
    data_dictionary.py        generates a Markdown field reference straight from a DataContract (Phase 7)
  quarantine/        quarantine record model + append-only store (Phase 2 — done)
  pii/                PII hashing + governed record model/store (Phase 3 — done)
    hashing_service.py     HMAC-SHA256, keyed via env var or explicit key; normalizes before hashing
    governed_models.py      GovernedLoanRecord (nullability mirrors what the contract actually guarantees)
    governed_store.py        append-only writer into governed.loan_record
  reference_data/     versioned CCF / risk-weight tables, seeded like rbac.role (Phase 4 — done)
    models.py              RegulatoryParameterSet (in-memory, loaded once — mirrors DataContract)
    store.py                list_versions / load / get_active, same pattern as ContractRegistry
  risk_engine/         EAD / EL / RWA calculators + calc-exception routing (Phase 4 — done)
    calculator.py            pure EAD/EL/RWA formulas (no grade dependency, by design)
    maturity.py               reporting-period-end bucketing (0-12M/13-36M/37-60M/60M+)
    engine.py                  pure engine over an in-memory RegulatoryParameterSet
    store.py                    persists metrics.loan_risk_metrics + calculation_exception
    gateway.py                   loads active parameters -> engine -> persists
  aggregation/          schedule aggregation engine, idempotent upsert (Phase 5 — done)
    models.py                ScheduleAggregate (reporting_period x segment x grade x bucket)
    engine.py                 pure group-by/SUM/COUNT over LoanRiskMetrics
    store.py                   upsert on the aggregate PK; new schema_version = retained history
    gateway.py                  reads a risk-calc run's metrics -> aggregates -> upserts
  catalog/               data product catalog + RBAC-scoped query sandbox (Phase 6 — done)
    models.py                DataProductCatalogEntry, SchemaVersionHistoryEntry
    health.py                 compute_sla_status (freshness-based), compute_health_score (weighted)
    store.py                   upserts the catalog entry; schema version history is append-only
    gateway.py                  update_after_run: DQ% + SLA + health score, after each pipeline run
    query_sandbox.py             typed, RBAC-gated read methods over ScheduleAggregate — no write surface
  rbac/                   role-permission matrix + RbacService (Phase 3 — done)
    matrix.py                ROLE_PERMISSION_MATRIX (design doc §2.9 + v2.0 §2.12 additions)
    service.py                RbacService.has_permission / require_permission
  audit/                   lineage/audit event logging (Phase 7 — done)
    models.py                  AuditEvent
    store.py                    append-only writer/reader for audit.event_log
    logger.py                    AuditLogger — the convenience entry point every gateway/service uses
  orchestrator/            full run sequencing under one pipeline_run_id (Phase 7 — done)
    models.py                  ChannelSource, PipelineRunReport
    retry.py                    retry_on_transient_error (linear backoff, configurable exceptions)
    orchestrator.py               sequences ingestion(N channels)->validation->risk->aggregation->catalog,
                                   emitting an audit event per stage, all under one pipeline_run_id
  scenario/                Scenario Reference Store + Stress Engine: supervisory scenarios,
                           translation tables, ScenarioSpec, stressed EAD/EL/RWA (Phase 8, C27/C28)
  mcp_server/              MCP Tool Server: typed tool interface over C1-C16, C27, C28 (Phase 9, C23)
  policy/                  Policy Enforcement Point: ToolPolicy eval, autonomy decisions (Phase 9, C24)
  approval_queue/          Approval Queue Service: agent proposals, four-eyes approval routing (Phase 9, C25)
  agent_trace/             Agent Trace Store: sessions, plans, tool calls, policy decisions (Phase 9, C26)
  pii_egress/              PII Egress Guard: blocks PII leakage in agent-bound outbound payloads (Phase 9, C31)
  agent_runtime/           Agent Runtime: supervisor/specialist graph, checkpointing (Phase 10, C17)
  grounding/               Numeric Grounding Checker: binds narrative figures to tool-output fields (Phase 11, C29)
  evaluation/              Evaluation harness: golden-set scenario/triage/grounding/guardrail tests (Phase 12, C30)
  api/                     FastAPI surface (sandbox, catalog, ingestion endpoints)
  db.py                    DuckDB bootstrap — applies schemas/*.sql
  demo.py                  `fry14 demo` — runs the real pipeline end-to-end, prints a report
  cli.py                   `fry14` command-line entry point

schemas/            versioned DDL per logical zone: landing, quarantine, governed,
                    metrics, aggregates, catalog, reference, rbac, audit, contracts
                    (v1.0 zones) + scenario, agent_governance (v2.0 zones)
config/contracts/   authored source-of-truth contract YAML, one subdir per contract_id,
                    one file per version (e.g. commercial_loan/1.0.0.yaml)
tests/
  unit/             component-level tests (models, adapters, generator, contracts, validation)
  integration/       cross-component tests (DB bootstrap, ingestion runs, validation gateway)
```

Agents AG-1..AG-5 don't each get a top-level package — they're implementations hosted inside
`agent_runtime/`'s supervisor/specialist graph, per the design doc's own component grouping.

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
```

The `agentic` extra (`pip install -e ".[agentic]"`) adds the Phase 9+ dependencies
(LangGraph, MCP SDK, Anthropic client, sqlglot, OpenTelemetry, Streamlit) — **not yet installed
or exercised in this repo**; it's documented in `pyproject.toml` ahead of need. Don't install it
until Phase 9 actually starts.

## Bootstrap the local database

The engine uses a local DuckDB file (`data/fry14_engine.duckdb`, git-ignored)
with one logical schema per governance zone. Create/update it with:

```bash
python -m fry14_engine.db
```

This applies every file in `schemas/` (in filename order) and is safe to
re-run (idempotent `CREATE SCHEMA/TABLE IF NOT EXISTS`).

## See it run

```bash
fry14 demo
```

A single `Orchestrator.run()` call sequences: generate synthetic loan
records, ingest them through both the batch-file and event-stream
adapters, validate against the active `commercial_loan` contract (hashing
PII regardless of pass/fail, routing to the governed or quarantine store),
compute EAD/EL/RWA for every governed record, aggregate into
schedule-shaped rows (reporting period x segment x grade x maturity
bucket), and update the data product catalog (health score, DQ %, SLA
status) — all under **one `pipeline_run_id`**. The demo then runs one
allowed query-sandbox request (as `FINANCE`) and one denied one (as
`DATA_ENGINEER`), and reconstructs the full run from the audit log using
that same id. Prints a report covering every stage, including the audit
trail. This exercises the real Phase 0-7 code paths — nothing is mocked
(the PII hashing key is a hardcoded dev-only default so the demo runs with
no setup; see `demo.py` for why that's never acceptable outside a demo).
Options: `--count`, `--bad-rate`, `--seed`, `--db-path` (defaults to
`data/demo.duckdb`, separate from the main bootstrap DB). See
[`RUNBOOK.md`](RUNBOOK.md) for how to interpret the output and reconstruct
a run from its `pipeline_run_id` outside the demo.

```bash
fry14 data-dictionary
```

Prints a Markdown field reference generated directly from the active
contract's definitions — never hand-maintained, so it can't drift from
what's actually enforced.

## Run tests

```bash
pytest -q                                           # full suite
pytest -q --cov=fry14_engine --cov-report=term-missing   # with coverage
ruff check src tests                                 # lint
black --check src tests                              # format check
```

## CLI

```bash
fry14 version
```

## Status

This repo implements the **v2.0 (agentic)** spec. Of the full 12-phase plan
(see `03-implementation-plan.md` §2):

- **Phases 0–3 complete**: project scaffolding, storage schema DDL (including
  the v2.0 `scenario` and `agent_governance` zones), the shared
  ingestion-metadata utility, both ingestion adapters (batch file + event
  stream), the append-only landing store, a synthetic loan record generator,
  the YAML-backed contract registry (DB-mirrored into `contracts.*`), the
  validation engine (all applicable reason codes per record, not just the
  first), the quarantine store, PII hashing (HMAC-SHA256, deterministic,
  keyed), the governed store, and the role-permission matrix / `RbacService`.
  Quarantined and governed records both carry real hashes now — no raw PII
  persists anywhere, verified by an automated scan test.
- **Phase 4 complete**: the Reference Data Store (versioned CCF/risk-weight
  tables, seeded like `rbac.role`), the pure EAD/EL/RWA calculators and
  maturity bucketing, and the Risk Metric Engine — which routes missing
  PD/LGD, a missing maturity date, or an unrecognized asset class to a
  calculation exception rather than defaulting or crashing, same
  fail-forward principle as contract validation. EAD/EL/RWA are rounded to
  cents at calculation time so the in-memory values match exactly what the
  `DECIMAL(18, 2)` metrics columns persist — a real discrepancy caught
  while building this phase, not a hypothetical.
- **Phase 5 complete**: the Aggregation Engine groups `LoanRiskMetrics` by
  reporting period x portfolio segment x credit grade x maturity bucket
  into `ScheduleAggregate` rows (SUM(EAD/EL/RWA), COUNT(loans)). Persistence
  is an upsert keyed on those four dimensions plus `schema_version` — a
  same-version re-run overwrites cleanly (idempotent re-aggregation,
  verified by a test that re-runs and checks totals don't double), while a
  *new* `schema_version` is retained as separate history, not an overwrite.
- **Phase 6 complete**: the Data Product Catalog (health score = 70% DQ
  pass rate + 30% SLA adherence, a transparent documented formula, not a
  black box; SLA status is freshness-based — ON_TIME/AT_RISK/BREACHED off
  how long ago the last run completed) and the Query Sandbox (typed,
  parameterized read methods over `ScheduleAggregate`, RBAC-gated via the
  existing `QUERY_SANDBOX_READ` permission — `FINANCE`/`RISK`/
  `REGULATORY_REPORTING`/`COMPLIANCE_AUDIT`/`ADMIN` can query it,
  `DATA_ENGINEER` and `SYSTEM_SCHEDULER` cannot). Per the design doc's own
  allowance, the "Operational Dashboard" for this phase is the `fry14 demo`
  report (a documented "UI-equivalent"), not a web UI — no HTTP/API layer
  has been built in any phase so far.
- **Phase 7 complete**: the Lineage & Audit Log Service (`audit.event_log`,
  one `AuditLogger.log()` call per stage, reconstructable end-to-end from
  `pipeline_run_id` alone) and a real `Orchestrator` that sequences every
  stage — multi-channel ingestion, validation/PII/governance, risk
  calculation, aggregation, catalog update — under **one** `pipeline_run_id`
  (replacing `demo.py`'s earlier ad-hoc per-stage ids), with retry-on-
  transient-failure at each stage. A capstone end-to-end test verifies the
  full chain reconciles through every layer by that one id, plus a reduced-
  scale (5,000-record) performance smoke test. **A genuine ~100x
  performance bug was found and fixed while building that smoke test**:
  DuckDB's Python `executemany` has very high per-call overhead; every
  store now uses a single multi-row `INSERT` instead (see
  `common/db_helpers.py` and `RUNBOOK.md` §6) — 5,000 records went from a
  failing 60s+ to ~8s. Documentation pass: `RUNBOOK.md` (run/interpret/
  troubleshoot/reconstruct-a-run) and a contract-generated data dictionary
  (`fry14 data-dictionary`).
- **Phase 8 is the earliest agentic-layer phase** (Scenario Reference Data &
  Stress Engine); it depends only on Phase 4 (complete) and can run in
  parallel with Phases 5–7 (all now complete). Phases 9–12 (MCP
  server/policy/audit, agent runtime + AG-1/AG-2, AG-3/AG-4/AG-5 + UI,
  evaluation/red-teaming) follow in sequence after Phase 8.

None of the agentic-layer code (`agent_runtime/`, `mcp_server/`, `policy/`,
`approval_queue/`, `agent_trace/`, `scenario/`, `grounding/`, `evaluation/`,
`pii_egress/`) is implemented yet — those are currently empty placeholder
packages, same as `contracts/`, `pii/`, `rbac/`, etc. were before Phase 2.

**Deferred from Phase 3 (explicitly, per the implementation plan's own
"optional/stretch" framing):** the Re-identification Vault (C8). Its DDL
(`governed.pii_reidentification_vault`) exists from Phase 0, but nothing
writes to or reads from it yet — `COMPLIANCE_AUDIT`/`ADMIN` RBAC gating for
`VIEW_RAW_PII` is built and tested, there's just no protected resource to
gate yet.
