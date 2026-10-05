# Implementation Plan: Governed Agentic Data Product Orchestrator & Stress Scenario Agent (FR Y-14 / CCAR)

**Version 2.0 (agentic)** · Phases 0–7 build the deterministic engine (unchanged from v1.0). Phases 8–12 add the stress engine and the governed agentic layer.

Companion to `01-approach-paper.md` and `02-design-document.md`. This plan sequences delivery into phases, defines the work breakdown, suggested tech stack, test strategy, and acceptance criteria tied back to `requirements.md`.

---

## 1. Recommended Technology Stack

| Concern | Choice | Rationale |
|---|---|---|
| Core processing language | Python 3.11+ | Rich data tooling (pandas/Polars), fast to implement rule engines and calculators, easy to unit test |
| Storage | PostgreSQL (or DuckDB for a lighter-weight/local demo) | Supports logical schemas per zone, transactional guarantees for quarantine/catalog updates, SQL for aggregation and sandbox queries |
| Event-driven ingestion simulation | Lightweight queue (e.g., Redis Streams, or an embedded file-based append log) | Enough to demonstrate event-driven ingestion without a heavy broker |
| Contract/schema definitions | JSON Schema + custom YAML rule extensions | Declarative, versionable, human-readable, diffable in version control |
| Orchestration | Simple DAG runner (e.g., Prefect, or a custom lightweight scheduler script) | Enough for sequencing C1→C12 without infra overhead |
| API layer | FastAPI | Typed, fast to stand up REST endpoints + auto-generated OpenAPI docs for the sandbox/catalog APIs |
| Dashboard | Minimal server-rendered page or a small React/Streamlit app | Sufficient to visualize catalog health/DQ/SLA and provide the query sandbox UI |
| Secrets / hashing key | Environment-variable-injected secret (local), with a note to use a real secrets manager (Vault/KMS) in production | Keeps PII hashing key out of source control |
| Testing | pytest | Unit + integration testing for calculators, validation engine, RBAC |
| Agent runtime *(v2.0)* | LangGraph (or Claude Agent SDK) | Stateful supervisor/specialist graph with checkpointing for pause-and-resume on confirmations and approvals |
| Tool interface *(v2.0)* | MCP Python SDK (FastMCP) | Typed tools over existing FastAPI services; single choke point for policy and logging |
| LLM *(v2.0)* | Pinned frontier model via enterprise endpoint (e.g., Claude via Anthropic API or Amazon Bedrock) | Version pinning, no-training/retention controls, strong structured-output and tool-use reliability |
| Structured outputs *(v2.0)* | Pydantic | Validates every agent output and tool schema |
| SQL guard *(v2.0)* | sqlglot | Parses and allow-lists AG-5 generated SQL |
| Agent tracing *(v2.0)* | OpenTelemetry + Langfuse (self-hosted) | Visual trace review; C26 Agent Trace Store remains system of record |
| Evaluation *(v2.0)* | pytest-based golden-set harness (optionally promptfoo) | Runs in CI; gates model/prompt/policy changes |
| Agent UI *(v2.0)* | Streamlit chat + approval queue + scenario comparison pages | Fast to build; same app as the operational dashboard |

> These are recommendations, not hard requirements — substitute per existing team/platform standards if constraints exist (e.g., if the organization standardizes on Spark/Databricks or a specific cloud data warehouse, the architecture in `02-design-document.md` maps cleanly onto those platforms too).

---

## 2. Phased Delivery Plan

### Phase 0 — Foundations (Week 1)
- Set up repo structure, environment, CI skeleton, linting, pytest scaffolding.
- Stand up storage schemas (empty tables) for: landing, quarantine, governed, metrics, aggregates, catalog, audit, reference data.
- Define `pipeline_run_id` generation and the `IngestionMetadata` stamping utility.
- **Deliverable**: empty-but-wired pipeline skeleton; schemas created; CI runs green on a trivial test.

### Phase 1 — Ingestion & Metadata Stamping (maps to req 2.1) (Week 1–2)
- Implement `BatchFileAdapter` (CSV/JSON file ingestion of synthetic loan/counterparty/credit-performance records).
- Implement `EventStreamAdapter` (simulated event-driven feed).
- Implement `MetadataStamper` and Landing Store writer (append-only).
- Build synthetic data generator (loans, counterparties, credit performance) with intentionally-seeded bad records for later testing of quarantine logic.
- **Tests**: ingestion of N records produces N landing rows, each with complete, correctly-populated `_ingestion_metadata`.
- **Deliverable**: Can ingest a sample batch file and a sample event stream into the landing zone with full metadata.

### Phase 2 — Contract Enforcement & Exception Handling (maps to req 2.2) (Week 2–3)
- Build `DataContract` schema format + Contract Registry (versioned storage, e.g., files or a DB table).
- Author the initial v1.0.0 contract for commercial loan records (types, ranges, non-null, enums per §2.2 of design doc).
- Implement `ValidationEngine`: multi-rule evaluation producing all applicable reason codes per record.
- Implement routing: valid → next stage continues; invalid → Quarantine Store with reason codes; **verify the valid stream is never blocked by invalid records in the same batch.**
- **Tests**: seeded bad records (negative balance, missing credit score, out-of-range grade) are correctly quarantined with correct reason codes; valid records in the same batch are unaffected; DQ pass/fail % computed correctly.
- **Deliverable**: Running a mixed-quality batch produces a governed valid stream + a fully reason-coded quarantine set.

### Phase 3 — PII Governance (maps to req 2.3) (Week 3)
- Implement `PIIHashingService` (HMAC-SHA256, keyed by secret) applied to SSN/EIN, legal name, address fields — applied to **both** valid and quarantined records before persistence.
- Implement RBAC module (role table + permission matrix) and wire `VIEW_RAW_PII` as a gated permission.
- (Optional/stretch) Implement `ReidentificationVault` for Compliance/Audit-only reversible lookup, fully audit-logged.
- **Tests**: no raw PII value appears in any persisted store (landing-post-hash, quarantine, governed) — automated scan asserts this; only `COMPLIANCE_AUDIT`/`ADMIN` roles can call the re-identification endpoint (if built); unauthorized attempts are logged and denied.
- **Deliverable**: All downstream data is demonstrably PII-hashed; RBAC enforcement proven via automated access-control tests.

### Phase 4 — Risk Metric Engine (maps to req 2.4, part 1) (Week 4)
- Build Reference Data Store: CCF table, risk-weight table, asset classification mapping, versioned.
- Implement `EAD`, `EL`, `RWA` pure calculation functions per formulas in design doc §3.5.
- Implement maturity bucketing logic.
- Wire calculation exception handling (e.g., missing PD/LGD → `CALC_MISSING_PD_LGD`, routed to a calc-exception queue, not silently defaulted).
- **Tests**: formula unit tests against hand-computed expected values for representative loans (including edge cases: zero commitment, 100% CCF, boundary credit grades); reproducibility test — same input + same reference version run twice yields identical output.
- **Deliverable**: Governed loan records produce correct, versioned `LoanRiskMetrics`.

### Phase 5 — Schedule Aggregation (maps to req 2.4, part 2) (Week 4–5)
- Implement `AggregationEngine` group-by (reporting period × portfolio segment × credit grade × maturity bucket) with SUM/COUNT measures.
- Implement idempotent re-aggregation / supersession logic for reprocessing a period.
- **Tests**: aggregate totals reconcile exactly against sum of underlying `LoanRiskMetrics`; re-running aggregation for the same period doesn't double-count.
- **Deliverable**: `ScheduleAggregate` rows ready for catalog/consumption.

### Phase 6 — Catalog & Consumer Interface (maps to req 2.5) (Week 5–6)
- Implement `CatalogService`: health score computation, DQ pass/fail %, schema version history tracking, SLA status evaluation.
- Build minimal **Operational Dashboard** (web page or Streamlit) rendering catalog entries.
- Implement `QuerySandboxService` (read-only API ± simple query UI) scoped to `FINANCE`, `RISK`, `REGULATORY_REPORTING` roles.
- **Tests**: dashboard reflects correct DQ %/SLA status after a run; sandbox returns data for permitted roles and is denied for non-permitted roles; sandbox cannot execute write operations (attempted write requests rejected).
- **Deliverable**: Fully working catalog + sandbox demonstrating governed self-service consumption.

### Phase 7 — Cross-Cutting Hardening & End-to-End Validation (Week 6–7)
- Wire `Lineage & Audit Log Service` across every component (if not already incrementally done per phase).
- Orchestrator (`C16`): full run sequencing, retry behavior, idempotency guarantees across a complete run.
- End-to-end test: synthetic batch → quarantine split → PII hash → risk calc → aggregation → catalog update → sandbox query, verified in one integration test.
- Performance pass against the NFR target (e.g., batch of ~100K synthetic records within SLA window).
- Documentation pass: README, runbook, data dictionary generated from contract definitions.
- **Deliverable**: Production-quality demonstration system meeting all approach-paper success criteria.

### Phase 8 — Scenario Reference Data & Stress Engine (maps to req AG-3.3–AG-3.7) (Week 8)
*Deterministic; can start in parallel with Phases 5–6 because it depends only on Phase 4.*
- Load Fed supervisory scenarios (Baseline, Severely Adverse, 9 quarters) into the Scenario Reference Store (C27) as versioned reference data.
- Author an illustrative `ScenarioTranslationTable` v1.0.0 (PD/LGD/drawdown betas by segment, grade sensitivity, floors/caps) with a written methodology note; approval workflow with four-eyes.
- Implement `ScenarioSpec` model and the deterministic `build_scenario_spec` validator (bounds, scope, versions, classification).
- Implement the Stress Engine (C28) per design §3.18: stressed PD/LGD/CCF → EAD/EL/RWA per loan per quarter; grade migration via `GradePDGrid`; static balance sheet; illustrative 9-quarter loss.
- Implement `ScenarioRunResult` aggregation with baseline vs. stressed deltas and `input_hash`.
- **Tests**: hand-calculated fixtures per formula; PD shock changes EL but not RWA; drawdown shock changes EAD/EL/RWA; clamps and caps; replay with same `input_hash` gives identical output; unapproved table rejected.
- **Deliverable**: Stress scenarios run end-to-end through an API with no LLM involved.

### Phase 9 — MCP Tool Server, Policy Enforcement & Agent Audit (maps to req 3.3–3.5) (Week 9)
- Build the MCP Tool Server (C23) with tools from `requirements.md` §3.3 wrapping existing service APIs.
- Implement `ToolPolicy` config and the Policy Enforcement Point (C24) per design §3.14, including conditional escalation (e.g., publish → PROPOSE when DQ < threshold).
- Implement RBAC extensions (design §2.12) and on-behalf-of identity; `SYSTEM_SCHEDULER` service principal.
- Implement Approval Queue Service (C25) with four-eyes enforcement and execution under approver identity.
- Implement Agent Trace Store (C26) and PII Egress Guard (C31).
- **Tests**: policy unit tests for every tool × role × autonomy combination; agents cannot reach `APPROVE_*`, reference-data writes, or re-identification; four-eyes enforced; seeded PII in an outbound payload is blocked.
- **Deliverable**: Tools callable from any MCP client with policy and audit enforced, before any agent exists.

### Phase 10 — Agent Runtime, AG-1 and AG-2 (maps to req AG-1, AG-2) (Week 10–10.5)
- Stand up the Agent Runtime (C17): supervisor graph, checkpointing, session limits, pinned model and prompt versions.
- Implement AG-1 Pipeline Operations Agent: plan display, tool-only execution, threshold checks, escalation, `RunReport`.
- Implement deterministic `get_quarantine_summary` tool (clusters + capped hashed samples).
- Implement AG-2 Data Quality Triage Agent: root-cause hypotheses with cited statistics; remediation, contract amendment, and source-ticket proposals; reprocessing hand-off after approval.
- Extend the synthetic data generator with **labeled root-cause scenarios** (e.g., a source feed drops credit scores after a schema change; one entity sends negative balances) for evaluation.
- **Tests**: Flow A from design §4.1 runs end-to-end; publish is blocked on DQ breach; no data change without recorded approval; reprocessed records keep lineage to quarantine IDs.
- **Deliverable**: Agent-operated pipeline with governed exception triage.

### Phase 11 — AG-3, AG-4, AG-5 and Agent UI (maps to req AG-3 to AG-5, 3.6) (Week 11–12)
- Implement AG-3 Stress Scenario Agent: NL → draft spec → validation → clarifying question → plain-language confirmation → run → interpretation.
- Implement Numeric Grounding Checker (C29) with binding templates and unbound-number scan; implement AG-4 Executive Reporting Agent on top of it.
- Implement AG-5 Data Product Concierge with `query_sandbox` SQL guard and user-identity execution.
- Build the Agent UI: conversational workspace showing plan and tool calls, Approval Queue page, Scenario Comparison page (baseline vs. stressed by quarter/segment/grade).
- **Tests**: Flows B and C from design §4.1 end-to-end; narrative with an injected free number is blocked; concierge results equal direct sandbox queries; write/PII requests refused.
- **Deliverable**: All five agents usable from the UI.

### Phase 12 — Evaluation, Red-Teaming & Demo Packaging (maps to req AG-GOV-1 to AG-GOV-5) (Week 12)
- Build evaluation sets per design §3.21 (scenario translation ≥ 50 cases, triage, grounding, guardrails, prompt injection) and wire them into CI as a release gate.
- Red-team session: prompt injection via record fields and file contents, attempts to escalate permissions, attempts to obtain PII, requests to "just estimate" a number.
- Write the model inventory entry (purpose, limitations, controls, evaluation results) aligned with SR 11-7 principles.
- Measure latency and token cost per flow; record in the README.
- **Demo packaging**: architecture diagram, README leading with the business problem and control framework, a 3–4 minute demo video covering Flows A and B, and an evaluation results summary.
- **Deliverable**: Evaluated, documented, demo-ready governed agentic application.

---

## 3. Work Breakdown Structure (WBS) Summary

| WBS ID | Task | Phase | Owner Role (suggested) |
|---|---|---|---|
| 1.1 | Repo/env/CI setup | 0 | Data Engineer |
| 1.2 | Storage schema creation (all zones) | 0 | Data Engineer |
| 2.1 | Batch adapter | 1 | Data Engineer |
| 2.2 | Event adapter | 1 | Data Engineer |
| 2.3 | Metadata stamper | 1 | Data Engineer |
| 2.4 | Synthetic data generator | 1 | Data Engineer |
| 3.1 | Contract schema format + registry | 2 | Data Engineer |
| 3.2 | Validation engine + routing | 2 | Data Engineer |
| 3.3 | Quarantine store + reason codes | 2 | Data Engineer |
| 4.1 | PII hashing service | 3 | Data Engineer / Security |
| 4.2 | RBAC module | 3 | Data Engineer / Security |
| 4.3 | Re-identification vault (stretch) | 3 | Security |
| 5.1 | Reference data store + seed tables | 4 | Risk/Quant + Data Engineer |
| 5.2 | EAD/EL/RWA calculators | 4 | Risk/Quant + Data Engineer |
| 5.3 | Maturity bucketing | 4 | Data Engineer |
| 6.1 | Aggregation engine | 5 | Data Engineer |
| 6.2 | Idempotent re-aggregation | 5 | Data Engineer |
| 7.1 | Catalog service | 6 | Data Engineer |
| 7.2 | Dashboard UI | 6 | Data Engineer / Front-end |
| 7.3 | Query sandbox API + UI | 6 | Data Engineer |
| 8.1 | Lineage/audit wiring | 7 | Data Engineer |
| 8.2 | Orchestrator finalization | 7 | Data Engineer |
| 8.3 | End-to-end test + perf validation | 7 | QA / Data Engineer |
| 8.4 | Documentation | 7 | All |
| 9.1 | Supervisory scenario loader + Scenario Reference Store | 8 | Risk/Quant + Data Engineer |
| 9.2 | Translation table v1.0.0 + methodology note + approval workflow | 8 | Risk/Quant |
| 9.3 | `ScenarioSpec` model + validator | 8 | Data Engineer |
| 9.4 | Stress Engine + `ScenarioRunResult` | 8 | Risk/Quant + Data Engineer |
| 10.1 | MCP Tool Server | 9 | AI Engineer |
| 10.2 | Policy Enforcement Point + `ToolPolicy` config | 9 | AI Engineer / Security |
| 10.3 | RBAC extensions + on-behalf-of identity | 9 | Security |
| 10.4 | Approval Queue Service | 9 | Data Engineer |
| 10.5 | Agent Trace Store + PII Egress Guard | 9 | AI Engineer / Security |
| 11.1 | Agent Runtime (supervisor graph, checkpointing, limits) | 10 | AI Engineer |
| 11.2 | AG-1 Pipeline Operations Agent | 10 | AI Engineer |
| 11.3 | Quarantine summary tool + AG-2 Triage Agent | 10 | AI Engineer + Data Engineer |
| 11.4 | Labeled root-cause scenarios in data generator | 10 | Data Engineer |
| 12.1 | AG-3 Stress Scenario Agent | 11 | AI Engineer + Risk/Quant |
| 12.2 | Numeric Grounding Checker + AG-4 Reporting Agent | 11 | AI Engineer |
| 12.3 | AG-5 Concierge + SQL guard | 11 | AI Engineer |
| 12.4 | Agent UI (workspace, approvals, scenario comparison) | 11 | Front-end / AI Engineer |
| 13.1 | Evaluation sets + CI release gate | 12 | AI Engineer / QA |
| 13.2 | Red-team exercise | 12 | Security / QA |
| 13.3 | Model inventory entry | 12 | Risk / Model Risk liaison |
| 13.4 | Demo packaging (README, diagram, video, eval summary) | 12 | All |

---

## 4. Test Strategy

| Level | Focus |
|---|---|
| Unit | Each calculator (EAD/EL/RWA), validation rule evaluator, hashing function, bucketing logic, RBAC permission checks |
| Integration | Ingestion → contract validation → routing; PII hashing applied consistently across valid/quarantine paths; aggregation reconciliation |
| End-to-End | Full run from synthetic source files through to catalog + sandbox query, using a known seeded dataset with predictable expected outputs |
| Security | No raw PII at rest scan; unauthorized RBAC access attempts; sandbox write-attempt rejection |
| Regression | Reproducibility test: identical reruns produce identical `LoanRiskMetrics`/`ScheduleAggregate` given unchanged inputs and reference versions |
| Performance | Load test with ~100K+ synthetic records against the defined processing SLA |
| Stress engine *(v2.0)* | Formula fixtures, sensitivity-direction tests (AG-3.5), clamps, replay determinism via `input_hash` |
| Policy *(v2.0)* | Every tool × role × autonomy combination; four-eyes; agents never hold `APPROVE_*` |
| Agent evaluation *(v2.0)* | Golden sets for scenario translation, triage, grounding, guardrails, prompt injection (design §3.21), run in CI |
| Privacy *(v2.0)* | Automated scan of prompts, agent state, traces, and outbound LLM payloads for PII |
| Resilience *(v2.0)* | LLM endpoint disabled: scheduled deterministic run still completes and publishes (when DQ passes) |

---

## 5. Acceptance Criteria (traced to requirements.md)

| Requirement | Acceptance Criterion |
|---|---|
| 2.1 Multi-source ingestion | System ingests both a batch file and an event-stream source into a unified landing format |
| 2.1 Metadata stamping | 100% of landed records contain non-null `ingestion_timestamp`, `source_entity_code`, `pipeline_run_id`, `source_system_of_record` |
| 2.2 Contract validation | A defined contract correctly flags type/range/null violations with zero false negatives on seeded bad records |
| 2.2 Exception isolation | Seeded bad records land in quarantine with correct reason codes; valid records in the same batch are unaffected and processed fully |
| 2.3 PII obfuscation | No raw SSN/EIN/Name/Address value is found in any persisted store via automated scan; hashing is deterministic |
| 2.3 RBAC | Only `COMPLIANCE_AUDIT`/`ADMIN` roles can access unmasked/re-identified PII; all other roles are denied and the denial is logged |
| 2.4 Risk metric engine | EAD/EL/RWA computed per loan match hand-calculated expected values on test fixtures |
| 2.4 Schedule aggregation | Aggregates by period/segment/grade/maturity bucket reconcile exactly to the sum of underlying loan-level metrics |
| 2.5 Operational dashboard | Catalog displays health score, DQ pass/fail %, schema version history, and SLA status, updated after each run |
| 2.5 Consumer query sandbox | Finance/Risk/Regulatory Reporting roles can query aggregates read-only; write attempts are rejected; other roles are denied access |
| AG-1 Pipeline Operations | NL run request shows a plan, runs through tools only, and pauses with escalation when DQ < threshold |
| AG-2 Triage | ≥ 90% correct root cause + source on labeled scenarios; no change applied without recorded approval |
| AG-3 Stress Scenario | ≥ 95% golden-set spec accuracy; ambiguity triggers clarification; stressed results match fixtures exactly |
| AG-3.5 Metric sensitivity | PD shocks change EL but not standardized RWA; drawdown shocks change EAD and RWA |
| AG-4 Reporting | Grounding check blocks any narrative with an unbound figure |
| AG-5 Concierge | Answers equal direct sandbox queries; non-permitted roles denied; write/PII requests refused and logged |
| 3.4 Autonomy policy | Human-only and prohibited actions cannot be executed by agents; attempts are logged |
| AG-GOV-1 Audit | Any agent session is reconstructable from the trace store |
| AG-GOV-5 Injection | Seeded injection records produce no change in tool calls vs. clean baseline |
| Resilience | Deterministic run completes with the agentic layer disabled |

---

## 6. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Regulatory parameter tables (CCF/risk-weight) used are illustrative, not current official values | Clearly label reference data as "configurable/illustrative" and source-reference the standardized approach categories used; make them easily updatable |
| Synthetic data may not capture real-world messiness | Deliberately seed a range of edge cases (nulls, negatives, out-of-range grades, boundary maturities) in the generator (Phase 1) |
| PII hashing key management oversimplified for demo | Document clearly that production deployment requires a proper secrets manager/KMS and key-rotation policy |
| Scope creep toward full FR Y-14 XBRL filing format | Explicitly scoped out in approach paper §9; confirm with stakeholders before any phase expands into it |
| Single-node storage may not meet production-scale volumes | Architecture logically separates zones so a future migration to a distributed warehouse (e.g., Snowflake/BigQuery/Databricks) requires no redesign, only re-platforming |
| LLM produces plausible but invented figures *(v2.0)* | Agents never calculate; narratives use bindings; Numeric Grounding Checker blocks unbound numbers |
| Misinterpreted stress request *(v2.0)* | Typed `ScenarioSpec`, deterministic validation, clarifying questions, mandatory user confirmation |
| Prompt injection through data content *(v2.0)* | Data passed in delimited blocks; policy enforced in code; injection tests in release gate |
| PII leakage to the LLM provider *(v2.0)* | Tools return hashed/aggregated data only; PII Egress Guard blocks on detection |
| Model version deprecation or behavior drift *(v2.0)* | Pinned model ID; evaluation suite must pass before any model change |
| Illustrative stress tables mistaken for calibrated models *(v2.0)* | Methodology note, `EXPLORATORY`/illustrative labels on every output, approval-gated tables |
| Token cost and latency growth *(v2.0)* | Size-bounded tool outputs, per-session limits, cost logged per session |
| Agent scope creep *(v2.0)* | Agent roster and tool allowlists fixed in requirements; new tools require policy entries and evals |

---

## 7. Timeline Summary

| Phase | Duration | Cumulative |
|---|---|---|
| 0 — Foundations | 1 week | Week 1 |
| 1 — Ingestion | 1–1.5 weeks | Week 2 |
| 2 — Contract Enforcement | 1 week | Week 3 |
| 3 — PII Governance | 1 week | Week 3–4 |
| 4 — Risk Metric Engine | 1 week | Week 4 |
| 5 — Aggregation | 0.5–1 week | Week 5 |
| 6 — Catalog & Sandbox | 1–1.5 weeks | Week 6 |
| 7 — Hardening & E2E | 1 week | Week 7 |
| 8 — Scenario Reference & Stress Engine *(v2.0)* | 1 week | Week 8 |
| 9 — MCP, Policy & Agent Audit *(v2.0)* | 1 week | Week 9 |
| 10 — Agent Runtime, AG-1, AG-2 *(v2.0)* | 1–1.5 weeks | Week 10 |
| 11 — AG-3, AG-4, AG-5, Agent UI *(v2.0)* | 1.5 weeks | Week 11–12 |
| 12 — Evaluation, Red-Team, Demo *(v2.0)* | 1 week | Week 12 |

**Total estimated duration: ~12 weeks** for a single engineer, or ~8 weeks for a 2–3 person team, at demonstration/reference-architecture fidelity. Compress by running Phases 2/3 and 4/5 in parallel, and by starting Phase 8 alongside Phases 5–6 (it depends only on Phase 4).

### 7.1 Portfolio MVP Cut (~7–8 weeks, single builder)

For an interview portfolio, a narrower cut shows the full story sooner:

| Keep | Defer |
|---|---|
| Batch ingestion, contract validation, quarantine, PII hashing, EAD/EL/RWA, aggregation | Event-stream adapter |
| Simple catalog page (DQ %, SLA, schema version) | Re-identification vault |
| Stress Engine with Severely Adverse + ad-hoc shocks | Grade-migration shocks |
| MCP server, Policy Enforcement Point, Approval Queue, trace store | Full RBAC UI (seed roles via config) |
| AG-1, AG-2, AG-3, AG-4 with grounding | AG-5 Concierge |
| Core evaluation sets (scenario translation, grounding, guardrails) | Performance load testing at 1M records |

The deferred items don't change the architecture; each can be added later without redesign.

---

## 8. Next Steps

1. Confirm technology stack choices (or substitute organization-standard tooling), including the agent framework and LLM endpoint.
2. Confirm whether official FR Y-14 schedule field-level templates are required for this phase or deferred (affects Phase 5/6 scope).
3. Decide between the full plan (~12 weeks) and the Portfolio MVP cut (§7.1).
4. Draft the scenario translation table methodology note early, since Phase 8 tests depend on it.
5. Begin Phase 0 — repository and schema setup.
