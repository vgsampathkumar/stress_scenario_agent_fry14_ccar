# Approach Paper: Governed Financial Data Product Engine (FR Y-14 / CCAR)

## 1. Purpose and Scope

This paper defines the overall technical approach for building a **Governed Financial Data Product Engine** that automates ingestion, data quality governance, PII protection, capital/credit risk metric computation, and regulatory schedule generation in support of the Federal Reserve's **FR Y-14Q/M/A** reporting requirements and the **Comprehensive Capital Analysis and Review (CCAR)** stress-testing exercise.

The system treats regulatory reporting as a **data product**: a governed, versioned, quality-scored, discoverable dataset with a defined owner, SLA, schema contract, and consumer access layer — rather than a one-off ETL pipeline. This approach paper covers:

- The guiding principles and architectural philosophy
- The target state architecture at a conceptual level
- How each functional requirement area (2.1–2.5 in `requirements.md`) maps to an architectural capability
- Key design trade-offs and the rationale behind the chosen approach
- Non-functional requirements (NFRs) derived from the regulatory context
- Assumptions, constraints, and explicitly out-of-scope items

Companion documents:
- `02-design-document.md` — detailed component, data, and interface design
- `03-implementation-plan.md` — phased delivery plan, milestones, and work breakdown

## 2. Business Context

Bank Holding Companies (BHCs) and Intermediate Holding Companies (IHCs) subject to Federal Reserve supervision must submit the FR Y-14Q (quarterly), FR Y-14M (monthly), and FR Y-14A (annual) schedules, which feed CCAR capital adequacy stress testing. Regulators require:

- **Traceability**: every reported number must be traceable to a source record and transformation logic.
- **Data quality attestation**: firms must demonstrate controls over completeness, accuracy, and timeliness.
- **PII protection**: borrower-identifying data must be protected per internal and regulatory privacy policy (GLBA, internal data classification policy) while still allowing risk computation.
- **Auditability**: full lineage, versioned schema contracts, and reproducible calculations for exam and internal audit purposes.

This system is scoped as a **synthetic/demonstration-grade implementation** of such a pipeline (the requirements explicitly reference "synthetic commercial loan records"), suitable for a controlled engineering environment, proof-of-concept, or training/reference architecture — while following patterns that would scale into a production regulatory-reporting platform.

## 3. Guiding Principles

1. **Contract-first governance.** No data enters the risk-calculation domain without passing an explicit, versioned data contract. Contracts are schema + business rules, not just types.
2. **Fail-forward, never fail-stop.** Bad records are quarantined with reason codes; the pipeline for good records is never blocked by a rejected record (per requirement 2.2).
3. **Privacy by construction, not by redaction.** PII is irreversibly hashed (one-way) as close to ingestion as possible so that no downstream component — including the risk engine — ever needs to handle raw PII. Re-identification is a separate, tightly access-controlled capability for compliance/audit roles only.
4. **Deterministic, replayable calculations.** EAD/EL/RWA computations are pure functions of versioned inputs and versioned regulatory parameter tables (CCFs, risk weights), so a given reporting period's numbers can always be regenerated and reconciled.
5. **Everything is a governed data product.** Raw, cleansed, quarantined, and aggregated datasets are each registered in a catalog with owners, schema version, quality score, and SLA — not just the final regulatory schedules.
6. **Least-privilege access by role.** RBAC is enforced at the query/semantic layer, not just the storage layer, with PII unmasking as a distinct, audited privilege.
7. **Idempotent, metadata-rich pipelines.** Every record and every pipeline run is stamped with operational metadata enabling reprocessing, backfill, and audit without ambiguity.

## 4. Target-State Architecture (Conceptual)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SOURCE SYSTEMS (Synthetic)                          │
│   Commercial Loan Core | Counterparty/Exposure Feed | Credit Performance    │
└───────────────────────────────┬──────────────────────────────────────────── ┘
                                 │ batch (files) + event-driven (stream)
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 1 — INGESTION & METADATA STAMPING                                     │
│  • Multi-source adapters (batch file + event stream)                        │
│  • Operational metadata stamping (ingest_ts, source_entity_code,            │
│    pipeline_run_id, source_system_of_record)                                │
│  • Landing zone (raw, immutable, append-only)                               │
└───────────────────────────────┬──────────────────────────────────────────── ┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 2 — DATA CONTRACT ENFORCEMENT & EXCEPTION HANDLING                     │
│  • Schema/contract registry (versioned)                                     │
│  • Rule engine: type, range, null, referential checks                       │
│  • Router: valid → Layer 3 (continues) | invalid → Quarantine Store         │
│    (with exception reason codes)                                            │
└───────────────┬───────────────────────────────────────────┬───────────────── ┘
                │ valid records                             │ invalid records
                ▼                                           ▼
┌───────────────────────────────────────┐   ┌───────────────────────────────────┐
│ LAYER 3 — PII GOVERNANCE               │   │ QUARANTINE REPOSITORY             │
│  • PII detection (SSN/EIN, Name, Addr) │   │  • reason codes                   │
│  • One-way cryptographic hashing       │   │  • original payload (hashed PII)   │
│  • Tokenized surrogate key issuance    │   │  • remediation workflow hooks     │
└───────────────────┬───────────────────┘   └───────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 4 — CREDIT RISK METRIC ENGINE                                          │
│  • EAD calculator (balance + unadvanced commitment × CCF)                    │
│  • EL calculator (PD × LGD × EAD)                                            │
│  • RWA calculator (asset-class risk weight × EAD)                           │
│  • Regulatory parameter tables (PD/LGD grids, CCF table, risk-weight table) │
│  • Versioned calculation engine (reproducible, auditable)                   │
└───────────────────────────────┬──────────────────────────────────────────── ┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 5 — SCHEDULE AGGREGATION                                              │
│  • Group by: reporting period (YYYY-MM), portfolio segment, credit grade,   │
│    maturity bucket                                                          │
│  • Produce FR Y-14Q/M/A-shaped schedule outputs                            │
└───────────────────────────────┬──────────────────────────────────────────── ┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 6 — DATA PRODUCT CATALOG & CONSUMER INTERFACE                         │
│  • Catalog: health score, DQ pass/fail %, schema version history, SLA       │
│  • RBAC-governed query sandbox (Finance / Risk / Regulatory Reporting)      │
│  • Read-only self-service exploration                                      │
└─────────────────────────────────────────────────────────────────────────────┘

Cross-cutting: Audit Logging | RBAC/IAM | Lineage & Metadata Store | Observability
```

## 5. Requirement-to-Capability Mapping

| Requirement (from requirements.md) | Architectural Capability | Key Design Decisions |
|---|---|---|
| 2.1 Multi-Source Ingestion | Layer 1 — Ingestion Adapters | Separate batch (file-drop/SFTP-style) and event-driven (stream/queue) adapters behind a common normalized ingestion interface |
| 2.1 Operational Metadata Stamping | Layer 1 — Metadata Stamper | Every record enveloped with `ingestion_metadata` block before landing; immutable landing zone |
| 2.2 Contract Validation | Layer 2 — Contract Engine | Declarative, versioned JSON-Schema-like contracts + custom business rule DSL (ranges, enums, non-null) |
| 2.2 Automated Exception Isolation | Layer 2 — Router + Quarantine Store | Non-blocking fork; reason-coded quarantine; valid-record stream continues downstream without delay |
| 2.3 PII Obfuscation | Layer 3 — PII Governance | Deterministic keyed one-way hash (HMAC-SHA256) for SSN/EIN/Name/Address fields; raw PII never persisted beyond ingress buffer |
| 2.3 RBAC | Cross-cutting IAM + Layer 6 | Role-to-permission matrix; PII re-identification vault is a separate, heavily audited service used only by Compliance/Audit roles |
| 2.4 Credit Risk Metric Engine (EAD/EL/RWA) | Layer 4 — Calculation Engine | Pure, versioned calculation functions; regulatory parameter tables stored as governed reference data, not hardcoded |
| 2.4 Schedule Aggregations | Layer 5 — Aggregation Engine | Multi-dimensional group-by (period × segment × grade × maturity bucket) producing schedule-shaped outputs |
| 2.5 Operational Dashboard | Layer 6 — Catalog Service | Health score, DQ %, schema version history, SLA status surfaced via catalog API/UI |
| 2.5 Consumer Query Sandbox | Layer 6 — Query Sandbox | Read-only, RBAC-scoped SQL/API sandbox over aggregated (not raw) datasets |

## 6. Non-Functional Requirements (Derived)

| NFR Category | Requirement |
|---|---|
| **Auditability** | Every transformation step must emit lineage records; all calculations must be reproducible given (input snapshot, parameter version, code version). |
| **Data Quality** | DQ pass/fail % must be computed per batch/run and surfaced in the catalog; target ≥ 98% pass rate on synthetic data with alerting below threshold. |
| **Security & Privacy** | No raw PII at rest beyond a short-lived ingress buffer; hashing keys stored in a secrets manager; RBAC enforced at API layer, not just DB grants. |
| **Performance** | Batch ingestion of ~100K–1M synthetic loan records processed within a defined SLA window (e.g., < 30 min per run) suitable for local/demo-scale infra. |
| **Reliability** | Pipeline failures isolate at the record level; a single bad record must never fail an entire batch. |
| **Extensibility** | New asset classes, risk-weight tables, or schedule types must be addable via configuration/reference data, not code changes. |
| **Versioning** | Schema contracts, regulatory parameter tables, and calculation logic are all independently versioned and attributable. |
| **Observability** | Structured logs + metrics for ingestion volume, rejection rate, processing latency, catalog freshness. |

## 7. Key Design Decisions & Trade-offs

1. **One-way hashing vs. reversible encryption for PII.**
   - *Decision*: Use keyed one-way hashing (HMAC) for PII fields used only as linkage/identity keys downstream, since risk calculations never require the raw borrower identity — only a stable surrogate key.
   - *Trade-off*: If true re-identification is later required (e.g., regulator requests underlying loan detail), a separate secure vault keyed by the same hash must be maintained by Compliance — this is called out as a distinct, access-controlled capability rather than baked into the main pipeline.

2. **Fork-and-continue exception handling vs. fail-fast batch rejection.**
   - *Decision*: Per requirement 2.2, invalid records are isolated and the batch continues. This favors availability of the reporting pipeline over blocking on data quality issues, consistent with regulatory expectations that firms report with documented exceptions rather than miss filing deadlines.
   - *Trade-off*: Requires robust reason-coding and a remediation/reprocessing workflow so quarantined records aren't silently lost.

3. **Reference-data-driven risk engine vs. hardcoded formulas.**
   - *Decision*: PD/LGD grids, CCFs, and risk weights are modeled as versioned reference tables, not embedded constants, so regulatory parameter updates (e.g., Basel/Fed revisions) don't require code changes.
   - *Trade-off*: Adds a reference-data management capability (versioning, approval workflow) as additional scope.

4. **Catalog as a first-class component vs. a reporting afterthought.**
   - *Decision*: Treat the data product catalog as a core deliverable (health score, DQ %, SLA, schema history) rather than a dashboard bolted on at the end, because governed discoverability is explicitly a functional requirement (2.5).

5. **Synthetic-data scope.**
   - *Decision*: Because the requirement explicitly states "synthetic commercial loan records," the implementation plan targets a demonstration/reference architecture (e.g., single-node or lightweight cluster, file- or lightweight-DB-backed storage) rather than a full production core-banking integration, while keeping interfaces abstracted so a real-source adapter could be substituted later.

## 8. Assumptions

- Source data (loan records, counterparty exposures, credit performance feeds) is synthetic and generated/mocked for this system; no live core-banking connection is required.
- "Event-driven ingestion" can be satisfied with a message-queue-based or file-watch-based simulation; a full enterprise streaming platform is not mandated.
- Regulatory parameter tables (CCFs, risk weights, PD/LGD grids) will be seeded with publicly documented standardized approach values (e.g., Basel III standardized risk weights) for demonstration purposes, clearly labeled as reference data subject to governance update.
- The FR Y-14Q/M/A "schedule" outputs are modeled as structurally representative aggregation outputs (period × segment × grade × maturity), not a byte-for-byte replica of the official FR Y-14 XML/XBRL submission templates — full regulatory submission formatting is a stretch goal, not a baseline requirement, unless specified otherwise.
- A single consolidated relational/analytical data store (e.g., a columnar or relational database) is acceptable for raw/cleansed/quarantine/aggregate zones, logically separated by schema/namespace rather than requiring separate physical platforms.

## 9. Out of Scope (for this phase)

- Integration with real/production core banking or regulatory submission systems.
- Full enterprise IAM/SSO integration (RBAC will be modeled and enforced in-application with a role table, not integrated with an external identity provider).
- Official FR Y-14 XBRL/XML submission packaging and electronic filing to the Federal Reserve's reporting portal.
- Disaster recovery / multi-region high availability.
- Model risk management (MRM) validation of the risk metric formulas beyond implementing the stated formulas correctly.

## 10. Success Criteria

- All five functional requirement areas (2.1–2.5) have a working, demonstrable implementation.
- A sample run ingests synthetic loan data, quarantines intentionally-bad records with correct reason codes, hashes PII fields, computes EAD/EL/RWA per loan, aggregates into schedule-shaped outputs, and renders catalog health metrics + a read-only query sandbox.
- All calculations are reproducible: re-running the same input snapshot through the same contract/parameter versions yields identical output.
- RBAC demonstrably restricts unmasked PII access to a designated compliance/audit role only.
