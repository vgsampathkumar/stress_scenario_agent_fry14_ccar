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
- [`MODEL_INVENTORY.md`](MODEL_INVENTORY.md) — SR 11-7-aligned entry: purpose, limitations, controls, evaluation results
- [`REDTEAM.md`](REDTEAM.md) — the Phase 12 red-team session log (prompt injection, permission escalation, PII, estimation attempts)

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
    store.py               write + read_all/read_by_id/read_open_by_reason_code/
                            update_remediation_status (read side + status updates: Phase 10)
    summary.py               build_quarantine_summary: get_quarantine_summary's clustering
                              (reason_code x source_system x rejection day, null-field rates,
                              capped samples) — pure, DB-free (Phase 10, C19's deterministic tool)
  pii/                PII hashing + governed record model/store (Phase 3 — done)
    hashing_service.py     HMAC-SHA256, keyed via env var or explicit key; normalizes before hashing
    governed_models.py      GovernedLoanRecord (nullability mirrors what the contract actually
                             guarantees; original_quarantine_id added Phase 10 for reprocessing lineage)
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
  scenario/                Scenario Reference Store + Stress Engine (Phase 8, C27/C28 — done)
    models.py                  MacroVariable/ScenarioName/TranslationTarget, SupervisoryScenarioSet,
                                ScenarioTranslationTable, GradePDGrid
    reference_store.py           loads Fed supervisory scenarios, translation table, grade PD grid
    spec_models.py                 ScenarioSpec, PortfolioScope, AdhocShock, GradeMigration
    spec_validator.py                build_scenario_spec: bounds/approval-gate checks, sets classification
    stress_calculator.py              pure per-(loan, quarter) formulas: Δx, multipliers, stressed PD/LGD/CCF/EAD/EL/RWA
    input_hash.py                      SHA-256 of a ScenarioSpec's content (excl. scenario_spec_id) -> replay safety
    engine.py                            StressEngine: applies the calculator across every in-scope loan x quarter
    run_models.py                          StressedLoanMetrics, ScenarioComparisonRow, ScenarioRunResult
    spec_store.py, run_store.py              persist/read back scenario.* tables
    gateway.py                                 StressScenarioGateway: load -> engine.run -> persist, audited
  agent_trace/             Agent Trace Store (Phase 9, C26 — done)
    models.py                  AgentTraceEvent, AgentTraceEventType
    store.py                     append-only writer/reader for agent_governance.agent_trace_event,
                                  + count_tool_calls (session-limit enforcement)
    logger.py                      AgentTraceLogger — convenience entry point, mirrors AuditLogger
  approval_queue/          Approval Queue Service (Phase 9, C25 — done)
    models.py                  AgentProposal, ProposalDraft, ProposalType/ProposalStatus
    store.py                     persist/read back agent_governance.agent_proposal
    service.py                     ApprovalQueueService: four-eyes + approver-RBAC-gated
                                    approve/reject, stale-proposal expiry
  policy/                  Policy Enforcement Point (Phase 9, C24 — done)
    models.py                  ToolPolicy, ToolPolicyCondition, PolicyDecision/PolicyOutcome
    store.py                     loads ToolPolicy (+conditions) from agent_governance.tool_policy
    pep.py                          PolicyEnforcementPoint.decide(): agent-allowlist -> RBAC ->
                                     condition escalation -> session-limit -> autonomy ->
                                     always logs a POLICY_DECISION trace event
  mcp_server/              MCP Tool Server (Phase 9-10, C23 — done)
    models.py                  ToolContext (agent/role/session identity), ToolCallResult
    server.py                    McpToolServer: thin, policy-gated, trace-logged wrappers over
                                  13 of 13 §3.3 tools (ingest/validate/calculate/aggregate/
                                  publish/build+run_stress_scenario/query_sandbox/catalog/lineage/
                                  get_quarantine_summary/propose_remediation/propose_contract_change —
                                  apply_remediation has none at all: HUMAN_ONLY, never agent-callable)
  pii_egress/              PII Egress Guard (Phase 9, C31 — done)
    guard.py                  PiiEgressGuard: recursive SSN/EIN pattern scan over any JSON-like
                               payload; fail-closed (blocks, never redacts-and-continues)
  agent_runtime/           Agent Runtime (C17), AG-1..AG-5 (C18-C22) (Phases 10-11 — done)
    models.py                  SessionStatus, AgentSession, RunLimits, LlmClient Protocol
                                (no concrete implementation in src/ — see its own scope note)
    store.py                     persists/reads checkpointed AgentSession state
    runtime.py                     AgentRuntime: start/record_step/record_tool_call/record_tokens
                                    (each hard-limited), complete_structured (one retry, then
                                    escalate), await_confirmation/resume, finish
    ag1_pipeline_operations.py       PipelineOperationsAgent: the fixed ingest->validate->
                                     calculate->aggregate->check_thresholds->publish->report
                                     plan, entirely through McpToolServer -> RunReport
    ag2_data_quality_triage.py        DataQualityTriageAgent: get_quarantine_summary -> LLM
                                      root-cause hypotheses (structured, cited) -> AgentProposal
                                      -> (after approval) reprocess_after_approval, carrying
                                      original_quarantine_id lineage into the new governed rows
    ag3_stress_scenario.py              StressScenarioAgent (Phase 11): NL -> draft ScenarioSpec ->
                                        build_scenario_spec -> clarifying question if ambiguous ->
                                        plain-language confirmation -> run_stress_scenario ->
                                        deterministic interpret() (never a narrative w/ free numbers)
    ag4_executive_reporting.py           ExecutiveReportingAgent (Phase 11): drafts a {{token}}-bound
                                         template, resolves bindings against a real RunReport/
                                         ScenarioRunResult, runs the Grounding Checker, proposes
                                         NARRATIVE_RELEASE only if grounding PASSED
    ag5_data_product_concierge.py         DataProductConciergeAgent (Phase 11): NL question ->
                                          typed query_sandbox call (no SQL surface at all — see
                                          its own scope note) under the user's own RBAC
  grounding/               Numeric Grounding Checker (Phase 11, C29 — done)
    models.py                  GroundedNarrative, GroundingStatus, GroundingResult
    checker.py                   GroundingChecker.check(): resolves {{token}} bindings, scans the
                                  template's own literal text for any unbound number (excluding a
                                  dates/quarter-labels/regulation-names allowlist) — either failure
                                  mode sets grounding_status=FAILED and blocks release
    store.py                     persist/read back agent_governance.grounded_narrative
  evaluation/              Evaluation Harness (Phase 12, C30 — done)
    models.py                  EvalCase, EvalCaseResult, EvalSetResult (pass_rate/meets_bar)
    scenario_translation.py      RuleBasedScenarioTranslator (illustrative, not a model) +
                                  50 golden NL->expected-draft/clarification cases
    triage.py                      RuleBasedTriageTranslator (illustrative) + 18 golden
                                    quarantine-cluster-with-known-root-cause cases
    grounding_eval.py                 golden narrative fixtures scored against the real GroundingChecker
    guardrails.py                      6 attack attempts run against the real PEP/PII Egress
                                        Guard/Approval Queue
    prompt_injection.py                  instruction-like text in a free-text field -> real AG-1
                                          pipeline -> tool-call sequence diffed vs. a clean baseline
  api/                     FastAPI surface (sandbox, catalog, ingestion endpoints)
  db.py                    DuckDB bootstrap — applies schemas/*.sql
  demo.py                  `fry14 demo` — runs the real v1.0 pipeline end-to-end, prints a report
  agent_demo.py            `fry14 agent-demo` — runs all 5 agents end-to-end (the "Agent UI"
                           deliverable's CLI form — see its own module docstring), prints a report
  ui/                      `fry14 ui` — the Agent UI deliverable's Streamlit form (`ui` extra)
    app.py                     sidebar triggers run_agent_demo(); one tab per agent; a live
                                Approval Queue tab (real ApprovalQueueService) + Agent Trace tab
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

The `agentic` extra (`pip install -e ".[agentic]"`) adds LangGraph, the MCP SDK, the
Anthropic client, sqlglot, and OpenTelemetry — **still not installed or exercised in this
repo as of Phase 12**, by deliberate, repeatedly-documented choice: the Agent Runtime is
plain Python (no graph framework needed), and `LlmClient` stays a `Protocol` with zero
concrete implementations in `src/` (a real model client needs API credentials this
environment doesn't have). Install it only once an actual model integration is in scope.

The separate `ui` extra (`pip install -e ".[ui]"`) adds **only** Streamlit — **this one is
installed and exercised**: `fry14 ui` launches a real dashboard
(`src/fry14_engine/ui/app.py`) over the same agents/tools/policy stack the CLI demo drives.
It was split out from `agentic` specifically because it needs none of the LLM/graph/tracing
dependencies above — same `ScriptedLlmClient`, same real engines underneath.

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
fry14 agent-demo
```

Runs all five agents end-to-end through the real `McpToolServer` /
`PolicyEnforcementPoint` / `AgentRuntime` stack on top of a fresh AG-1 run:
AG-2 triages and reprocesses a labeled `MISSING_CREDIT_SCORE` cluster, AG-4
drafts and releases a grounded narrative over the run, AG-3 drafts +
confirms + runs a Severely Adverse scenario (AG-4 drafts a second grounded
narrative over it), and AG-5 answers a concierge question — then prints
the plan, every tool call's outcome, the Approval Queue's pending state,
and a scenario comparison table (the CLI form of the "Agent UI"
deliverable; see `agent_demo.py`'s own docstring for why). Only the LLM
itself is scripted (fixed, labeled-illustrative responses — no model
credentials are wired into this repo); every number comes from the real
deterministic engines. Options: `--count`, `--seed`, `--db-path` (defaults
to `data/agent_demo.duckdb`).

```bash
pip install -e ".[ui]"   # once — adds Streamlit only
fry14 ui
```

Launches the same agentic stack as a Streamlit dashboard
(`src/fry14_engine/ui/app.py`): a sidebar to trigger a fresh
`run_agent_demo()`, a conversational-workspace overview, one tab per
agent, a live **Approval Queue** tab (approve/reject buttons call the
real `ApprovalQueueService` — decisions here are governed, not UI-only
state), and an **Agent Trace** tab grouping every session's events.

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
- **Phase 8 complete**: Scenario Reference Data & the Stress Engine (C27/C28)
  — the first agentic-layer phase, and explicitly deterministic (no LLM
  involved anywhere in it). Illustrative, clearly-labeled Fed-style
  supervisory scenario data (`FED-2026`, `BASELINE`/`SEVERELY_ADVERSE`, 10
  quarters x 7 macro variables) and an approval-gated `ScenarioTranslationTable`
  (linear PD/LGD/drawdown betas by segment x asset class, grade-sensitivity
  scaling, floor/cap multiplier clamps) are seeded the same idempotent way as
  Phase 4's reference data. `build_scenario_spec` validates a `ScenarioSpec`
  deterministically — bounds-checks horizon/ad-hoc-shock magnitudes/grade
  migration, requires an `APPROVED` translation table (raising
  `ScenarioTableNotApprovedError` otherwise, never a silent fallback), and
  sets `classification` (`EXPLORATORY` if any ad-hoc shock or grade migration
  is present, else `SUPERVISORY`). The Stress Engine applies the jump-off-
  relative shock formula per loan per projection quarter against a **static**
  balance sheet (balances held at quarter-0 for the whole horizon), producing
  stressed PD/LGD/CCF/EAD/EL/RWA and baseline-vs-stressed
  `ScenarioComparisonRow` aggregates. **RWA has no PD term by
  construction** — a PD-only shock moves EL but leaves EAD and RWA
  identical across quarters; a drawdown-only shock moves EAD, EL, *and* RWA
  together (requirement AG-3.5, covered by dedicated tests, not just
  asserted). Every run's `input_hash` is a SHA-256 of the spec's *content*
  (excluding its random `scenario_spec_id`), so two independently-built specs
  with identical parameters replay to byte-identical stressed output — also
  tested directly. `StressScenarioGateway` wires it all together: loads the
  governed loans and baseline risk metrics for a `base_pipeline_run_id`,
  loads the reference data a spec names, runs the engine, persists the full
  result (`scenario.scenario_spec`, `scenario_run_result`,
  `stressed_loan_metrics`, `scenario_comparison`), and logs two audit events
  (new `AuditEventType.STRESS_SCENARIO`) under that same `pipeline_run_id`.
  The original course-corrected `scenario.scenario_spec` DDL was missing
  several fields `ScenarioSpec` actually needs (`portfolio_scope`,
  `adhoc_shocks`, `grade_migration`, etc.) — fixed directly in the schema
  file since nothing had been persisted yet, same precedent as Phase 3's
  governed-table nullability fix.
- **Phase 9 complete**: the MCP Tool Server (C23), Policy Enforcement Point
  (C24), RBAC extensions (§2.12 — already seeded by the earlier agentic
  course-correction), Approval Queue Service (C25), Agent Trace Store (C26),
  and PII Egress Guard (C31) — "tools callable from any MCP client with
  policy and audit enforced, *before any agent exists*," exactly the plan's
  own framing. The full 13-tool catalog from requirements.md §3.3 is seeded
  as `agent_governance.tool_policy` rows (required permission, autonomy
  level, agent allowlist, session call limit), the same idempotent
  seed-data convention as every other reference table in this project.
  `PolicyEnforcementPoint.decide()` is plain code — it never calls an
  LLM — and runs the full decision chain for every call: deny if the
  calling agent isn't on the tool's allowlist, deny if the user's RBAC role
  lacks the required permission, evaluate named boolean conditions (never
  an evaluated expression string — avoids building an `eval()`-shaped
  vulnerability) to escalate autonomy, deny once a session hits
  `max_calls_per_session`, then act on the resolved autonomy
  (`AUTONOMOUS`→allow, `CONFIRM`→require explicit confirmation first,
  `PROPOSE`→create an `AgentProposal` and never execute, `HUMAN_ONLY`/
  `PROHIBITED`→deny) — and always logs a `POLICY_DECISION` trace event,
  allow or deny. `ApprovalQueueService` enforces four-eyes (the approver
  must differ from `requested_by`, not from the proposing agent — an
  agent holds no identity of its own to recuse) and the approver's own
  RBAC permission before recording a decision; rejections require a
  reason. `McpToolServer` wraps 10 of the 13 catalog tools as thin,
  policy-gated, trace-logged calls into the existing Phase 1-8 gateways —
  `publish_data_product` is the conditional-escalation example from the
  design doc itself (`AUTONOMOUS` by default, escalates to `PROPOSE` when
  the run's DQ pass rate is below the catalog threshold, and the catalog
  is genuinely never touched once escalated — verified by an integration
  test asserting zero rows). The remaining 3 tools
  (`get_quarantine_summary`, `propose_remediation`,
  `propose_contract_change`) plus `apply_remediation` are seeded in the
  policy catalog (so coverage and testing of the catalog itself is
  complete) but have no tool wrapper yet — `get_quarantine_summary` is
  explicitly Phase 10's own deliverable per the implementation plan, and
  the other three need AG-2 (also Phase 10) to produce proposals worth
  wrapping; implementing them now would mean faking a tool that does
  nothing real. `PiiEgressGuard` recursively scans any JSON-like outbound
  payload for SSN/EIN-shaped strings and blocks (fail-closed) rather than
  redacting and continuing — its "unexpected-field name/address heuristic"
  half from the design doc is deferred since it needs contract-specific
  field knowledge a general-purpose, contract-agnostic guard shouldn't
  have. 100% test coverage on all five new packages (`agent_trace`,
  `policy`, `approval_queue`, `mcp_server`, `pii_egress`).
- **Phase 10 complete**: the Agent Runtime (C17) and the first two live
  agents, AG-1 Pipeline Operations (C18) and AG-2 Data Quality Triage
  (C19). The runtime is a plain, dependency-free Python state machine, not
  a specific graph framework — the design doc's own "Technology
  Considerations" lists that as non-binding, and the `agentic` extra is
  still not installed. It checkpoints session state after every step/tool
  call, enforces hard per-session limits (steps/tool calls/tokens, each
  ending the session with `LIMIT_REACHED`), and validates structured LLM
  output against a Pydantic schema with exactly one retry before
  escalating `StructuredOutputInvalidError`. `LlmClient` is a `Protocol`
  only — no concrete implementation (real or fake) lives in `src/`; a
  production client wrapping a real model is deferred until API
  credentials are actually in scope, same documented boundary as the
  `agentic` extra itself. AG-1's plan is fixed by the design doc itself
  ("ingest -> validate -> calculate -> aggregate -> check thresholds ->
  publish -> report"), so it's deterministic orchestration (the same shape
  as Phase 7's `Orchestrator`) routed entirely through the policy-enforced
  MCP tools — no live model call. It reports (never raises on) a
  `publish` permission denial, since `on_behalf_of` holding `RUN_PIPELINE`
  without `PUBLISH_DATA_PRODUCT` is separation-of-duties by design, not a
  bug — verified by a dedicated test. AG-2 calls the new
  `get_quarantine_summary` tool (clusters by reason code x source system x
  rejection day, with null-field rates and ≤20 capped sample ids — scoped
  down from the design doc's "source entity" dimension, which
  `quarantine.quarantine_record` has never actually captured), has the
  LLM form cited root-cause hypotheses over those clusters, and turns each
  into an `AgentProposal` (`REMEDIATION_RULE`/`CONTRACT_AMENDMENT`/
  `SOURCE_TICKET`) — it never edits data itself.
  `reprocess_after_approval` is gated on `proposal.status == APPROVED`,
  checked in code, not trusted from the caller (verified by a test that
  the un-approved path raises `NoDataChangeWithoutApprovalError` and
  changes zero rows); once approved, it corrects the quarantined field,
  re-validates against the real contract, and writes a new
  `GovernedLoanRecord` carrying the new `original_quarantine_id` lineage
  column — a genuine bug was caught here by a test, not inspection: the
  quarantined `outstanding_balance` is a JSON-serialized *string* (from
  `model_dump(mode="json")` at quarantine time), so `abs()` on it directly
  raised `TypeError`; fixed by parsing through `Decimal` first. The
  synthetic generator gained two labeled, attributable root-cause fixtures
  (`generate_schema_change_drops_credit_score_batch`,
  `generate_negative_balance_entity_batch`) so a correct triage has a
  deterministic ground truth to check against, not just a uniformly-cycled
  mix of defects. 99%+ test coverage on every new/touched module.
- **Phase 11 complete**: AG-3 Stress Scenario, the Numeric Grounding
  Checker (C29) + AG-4 Executive Reporting, AG-5 Data Product Concierge,
  and the "Agent UI" deliverable. AG-3's flow matches the design doc's own
  five steps exactly: an LLM drafts a `DraftScenarioRequest`;
  `build_scenario_spec` validates it deterministically (any
  `ScenarioSpecValidationError`/`ScenarioTableNotApprovedError`/
  `ScenarioReferenceNotFoundError` is caught and reported as `REJECTED`,
  never left to crash the caller); an ambiguous request gets a single
  clarifying question (`NEEDS_CLARIFICATION`) whose answer threads into a
  second draft; a plain-language summary waits for explicit confirmation
  (`run_stress_scenario`'s own seeded `CONFIRM` autonomy from Phase 9
  enforces this, not a convention); and `interpret()` is a deterministic
  template over the real `ScenarioRunResult` — AG-3 never writes free-form
  prose itself, that's AG-4's job. The Numeric Grounding Checker resolves
  `{{token}}` bindings against a real `RunReport`/`ScenarioRunResult`
  (rejecting a binding that names the *wrong* run id, not just any run),
  then scans the template's own literal text for any number that isn't a
  binding — excluding a small, explicit allowlist (quarter labels, dates,
  "FR Y-14"/"CCAR") — and fails closed on either an unresolved binding or
  an unbound number. AG-4 only creates a `NARRATIVE_RELEASE` proposal
  (via the Approval Queue directly — there's no MCP tool for narrative
  release in the §3.3 catalog) when grounding passes; a narrative that
  fails is persisted (for audit) but never proposed. AG-5 keeps Phase 6's
  `query_sandbox` exactly as built — a typed, parameterized method with no
  SQL-accepting surface at all — rather than retrofitting the design
  doc's "generate SQL, then parse and allow-list it" approach, since the
  existing architecture is structurally stronger (no injection surface to
  defend in the first place); a dedicated test confirms the concierge's
  answer is byte-identical to calling `QuerySandboxService` directly with
  the same parameters. The **Agent UI** deliverable has two forms: `fry14
  agent-demo` is a documented CLI report (same precedent as Phase 6's
  "Operational Dashboard"), and `fry14 ui` launches a real Streamlit
  dashboard (`src/fry14_engine/ui/app.py`, the `ui` extra —
  `pip install -e ".[ui]"`) over the same `run_agent_demo()` data, with
  a conversational-workspace overview, one tab per agent (AG-UI-1/AG-UI-4:
  the scenario comparison chart lives in the AG-3 tab), a live Approval
  Queue tab whose approve/reject buttons call the real
  `ApprovalQueueService` (AG-UI-3 — decisions made here are governed
  decisions, not UI-only state), and an Agent Trace tab grouping every
  session's events (AG-UI-2). Both forms share the same
  `ScriptedLlmClient` — fixed, labeled-illustrative structured responses,
  not a real model call — which lives in the demo module, not in
  `agent_runtime/` itself (`LlmClient` stays a `Protocol` with zero concrete
  implementations in `src/`). 99%+ test coverage on every new module.
- **Phase 12 complete (final phase)**: the Evaluation Harness (C30), a
  red-team session, the model inventory entry, latency measurement, and
  demo packaging. Five golden-set evaluation sets live in `evaluation/`
  and run as part of the normal test suite — i.e. already wired into CI
  (`.github/workflows/ci.yml`) as a release gate, with no new workflow
  needed. Two sets (scenario translation, triage) score an illustrative
  rule-based stand-in (no real `LlmClient` exists — see
  `agent_runtime/models.py`'s scope note, unchanged since Phase 9) against
  ≥50 and 18 golden cases respectively; honestly, scenario translation
  scores **94%** against its 95% bar (3 deliberately out-of-vocabulary
  phrasings a keyword parser can't handle) and triage scores 100%. The
  harness does not force a pass — a worse-than-reality 100% across the
  board would have been a red flag, not a win. The other three sets
  (grounding, guardrails, prompt injection) exercise real, already-shipped
  deterministic code and all clear 100%. See
  [`MODEL_INVENTORY.md`](MODEL_INVENTORY.md) for the full SR 11-7-aligned
  entry (purpose, limitations, controls, evaluation results — explicitly
  scoped to "no concrete model exists yet; this documents the governance
  framework a real one must pass through") and
  [`REDTEAM.md`](REDTEAM.md) for the 11-attempt red-team log (prompt
  injection via record fields, 5 permission-escalation vectors, 2 PII
  paths, "just estimate a number") — **11/11 blocked**, each attempt a
  runnable test, not a thought experiment. Illustrative latency (not
  token cost — no real model is deployed to meter): a full
  `fry14 agent-demo` run (all 5 agents, synthetic 24-record batch)
  completes in ~1.8s wall-clock on a dev machine; per-agent-session spans
  reconstructed from `agent_trace_event` timestamps range ~15–230ms.
  These numbers reflect local SQLite-grade DuckDB overhead and
  `ScriptedLlmClient`'s zero-latency responses, not a production model
  call — recorded for completeness, not as an SLA. **Demo packaging**:
  the architecture diagrams already exist (`docs/agentic_architecture.docx`,
  `docs/traditional_architecture.docx`, created earlier in this project);
  a 3–4 minute demo video is a human deliverable outside a coding agent's
  capability (no audio/video recording tool available) and is explicitly
  **not** produced here — `fry14 agent-demo`'s own printed report is the
  closest in-repo substitute for what that video would show. A real
  Streamlit Agent UI (`fry14_engine/ui/app.py`, `fry14 ui`) was found
  already built in the working tree during this phase — see the
  "Agentic layer roster" / "See it run" sections above for what it does;
  one genuine bug was caught integrating it into this suite: its
  top-level `main()` call was unconditional, so merely *importing* the
  module (not running it) executed the whole app in Streamlit's bare
  mode and corrupted global script-run state for any `AppTest`-based
  test that ran afterward in the same process. Fixed with the standard
  `if __name__ == "__main__":` guard — verified both `streamlit run`
  and `AppTest` still exercise it correctly (a fresh `AppTest` run now
  clicks "Run agent demo" and checks every tab populates; ~88% coverage
  on `ui/app.py`). CI (`.github/workflows/ci.yml`) now installs the `ui`
  extra alongside `dev` so this runs in CI too, not just locally.

None of the agentic-layer code from the implementation plan remains
unimplemented as placeholder packages — `evaluation/` is now real, closing
out all 12 phases.

**Deferred from Phase 3 (explicitly, per the implementation plan's own
"optional/stretch" framing):** the Re-identification Vault (C8). Its DDL
(`governed.pii_reidentification_vault`) exists from Phase 0, but nothing
writes to or reads from it yet — `COMPLIANCE_AUDIT`/`ADMIN` RBAC gating for
`VIEW_RAW_PII` is built and tested, there's just no protected resource to
gate yet.
