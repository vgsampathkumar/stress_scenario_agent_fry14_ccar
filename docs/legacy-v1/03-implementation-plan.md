# Implementation Plan: Governed Financial Data Product Engine (FR Y-14 / CCAR)

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

---

## 6. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Regulatory parameter tables (CCF/risk-weight) used are illustrative, not current official values | Clearly label reference data as "configurable/illustrative" and source-reference the standardized approach categories used; make them easily updatable |
| Synthetic data may not capture real-world messiness | Deliberately seed a range of edge cases (nulls, negatives, out-of-range grades, boundary maturities) in the generator (Phase 1) |
| PII hashing key management oversimplified for demo | Document clearly that production deployment requires a proper secrets manager/KMS and key-rotation policy |
| Scope creep toward full FR Y-14 XBRL filing format | Explicitly scoped out in approach paper §9; confirm with stakeholders before any phase expands into it |
| Single-node storage may not meet production-scale volumes | Architecture logically separates zones so a future migration to a distributed warehouse (e.g., Snowflake/BigQuery/Databricks) requires no redesign, only re-platforming |

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

**Total estimated duration: ~7 weeks** for a single engineer or small (2–3 person) team working the full scope at demonstration/reference-architecture fidelity. Compress by running Phases 2/3 and Phases 4/5 in parallel across two engineers if available.

---

## 8. Next Steps

1. Confirm technology stack choices (or substitute organization-standard tooling) with stakeholders.
2. Confirm whether official FR Y-14 schedule field-level templates are required for this phase or deferred (affects Phase 5/6 scope).
3. Begin Phase 0 — repository and schema setup.
