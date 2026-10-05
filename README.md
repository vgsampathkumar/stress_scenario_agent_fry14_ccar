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
  aggregation/          schedule aggregation engine (Phase 5)
  catalog/               data product catalog service (Phase 6)
  rbac/                   role-permission matrix + RbacService (Phase 3 — done; API-level wiring is Phase 6)
    matrix.py                ROLE_PERMISSION_MATRIX (design doc §2.9 + v2.0 §2.12 additions)
    service.py                RbacService.has_permission / require_permission
  audit/                   lineage/audit event logging (Phase 7)
  orchestrator/            pipeline run sequencing (Phase 7)
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

Generates synthetic commercial loan records, ingests them through both the
batch-file and event-stream adapters, validates them against the active
`commercial_loan` contract, hashes PII (HMAC-SHA256) regardless of pass/fail,
routes each record to the governed store or the quarantine store, then
computes EAD/EL/RWA for every governed record against the active
regulatory parameter set. Prints a report: records landed per channel, how
many were governed vs. quarantined, the DQ pass rate, a reason-code
breakdown, and risk-calculation totals (EAD/EL/RWA plus any calculation
exceptions). This exercises the real Phase 0-4 code paths — nothing in the
report is mocked (the PII hashing key is a hardcoded dev-only default so
the demo runs with no setup; see `demo.py` for why that's never acceptable
outside a demo). Options: `--count`, `--bad-rate`, `--seed`, `--db-path`
(defaults to `data/demo.duckdb`, separate from the main bootstrap DB). Each
run appends new rows (every zone is append-only by design) rather than
overwriting history.

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
- **Phase 5 is next**: Schedule Aggregation — unchanged from v1.0 (see
  `03-implementation-plan.md` Phase 5).
- Phases 6–7 (catalog/sandbox, cross-cutting hardening) remain the
  deterministic-engine build-out.
- **Phase 8 is the earliest agentic-layer phase** (Scenario Reference Data &
  Stress Engine); it depends only on Phase 4 (now complete) and can run in
  parallel with Phases 5–6. Phases 9–12 (MCP server/policy/audit, agent
  runtime + AG-1/AG-2, AG-3/AG-4/AG-5 + UI, evaluation/red-teaming) follow
  in sequence after Phase 8.

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
