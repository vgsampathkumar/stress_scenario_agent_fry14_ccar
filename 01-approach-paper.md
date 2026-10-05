# Approach Paper: Governed Agentic Data Product Orchestrator & Stress Scenario Agent (FR Y-14 / CCAR)

**Version 2.0 (agentic)** · supersedes v1.0 "Governed Financial Data Product Engine". Aligned to `requirements.md` v2.0.

## 1. Purpose and Scope

This paper defines the overall technical approach for building a **Governed Financial Data Product Engine** that automates ingestion, data quality governance, PII protection, capital/credit risk metric computation, and regulatory schedule generation in support of the Federal Reserve's **FR Y-14Q/M/A** reporting requirements and the **Comprehensive Capital Analysis and Review (CCAR)** stress-testing exercise.

The system treats regulatory reporting as a **data product**: a governed, versioned, quality-scored, discoverable dataset with a defined owner, SLA, schema contract, and consumer access layer — rather than a one-off ETL pipeline.

**What changes in v2.0.** A governed agentic layer now operates on top of the deterministic engine. Five AI agents run the pipeline, triage data quality exceptions, translate natural-language stress requests into structured scenarios, write executive summaries, and answer consumer questions. All calculations stay in deterministic, versioned code. Agents reach the engine only through typed tools exposed by an MCP server, and a deterministic policy layer enforces what each agent may do, with or without human approval.

This approach paper covers:

- The guiding principles and architectural philosophy
- The target state architecture at a conceptual level
- How each functional requirement area (2.1–2.5 in `requirements.md`) maps to an architectural capability
- Key design trade-offs and the rationale behind the chosen approach
- Non-functional requirements (NFRs) derived from the regulatory context
- Assumptions, constraints, and explicitly out-of-scope items
- The governed agentic layer: agent roles, tool interface, autonomy policy, and agent governance (new in v2.0: §2.1, §3 principles 8–12, §4.1, §5.2, §7 decisions 6–11)

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

### 2.1 Why an Agentic Layer (v2.0)

The deterministic engine solves computation and control. The remaining cost of regulatory data delivery is human coordination work around it:

- **Exception triage.** Data engineers spend significant time grouping quarantined records, finding the upstream cause, and drafting fixes.
- **Ad-hoc stress requests.** Risk and Finance leaders ask "what if" questions (rate shocks, CRE value declines, downgrades) that today require an analyst to translate the request, run models, and assemble results.
- **Commentary.** Every run and every scenario needs a written explanation for senior stakeholders.
- **Self-service.** Consumers who don't write SQL still depend on the data team for simple questions.

Agents can absorb much of this work, but in Finance and Risk an ungoverned LLM is unacceptable: invented numbers, unapproved data changes, or PII leakage would fail any model risk or audit review. The approach therefore treats **governance of the agents as a first-class design problem**, not an afterthought.

## 3. Guiding Principles

1. **Contract-first governance.** No data enters the risk-calculation domain without passing an explicit, versioned data contract. Contracts are schema + business rules, not just types.
2. **Fail-forward, never fail-stop.** Bad records are quarantined with reason codes; the pipeline for good records is never blocked by a rejected record (per requirement 2.2).
3. **Privacy by construction, not by redaction.** PII is irreversibly hashed (one-way) as close to ingestion as possible so that no downstream component — including the risk engine — ever needs to handle raw PII. Re-identification is a separate, tightly access-controlled capability for compliance/audit roles only.
4. **Deterministic, replayable calculations.** EAD/EL/RWA computations are pure functions of versioned inputs and versioned regulatory parameter tables (CCFs, risk weights), so a given reporting period's numbers can always be regenerated and reconciled.
5. **Everything is a governed data product.** Raw, cleansed, quarantined, and aggregated datasets are each registered in a catalog with owners, schema version, quality score, and SLA — not just the final regulatory schedules.
6. **Least-privilege access by role.** RBAC is enforced at the query/semantic layer, not just the storage layer, with PII unmasking as a distinct, audited privilege.
7. **Idempotent, metadata-rich pipelines.** Every record and every pipeline run is stamped with operational metadata enabling reprocessing, backfill, and audit without ambiguity.

8. **Agents orchestrate; code calculates.** No LLM produces, adjusts, or estimates a regulatory number. Every PD, LGD, EAD, EL, RWA, and aggregate comes from a deterministic, versioned tool. Agents plan, call tools, interpret, and explain.
9. **Autonomy is enforced by code, not by prompts.** A deterministic Policy Enforcement Point sits between agents and tools and decides allow / confirm / propose / deny for every call. Prompt instructions are a convenience, never a control.
10. **Humans approve changes; agents propose them.** Agents may draft remediation rules, contract amendments, and narratives, but changes to data, contracts, reference data, or published products need a named human approver with the right role (four-eyes for contract and reference-data changes).
11. **Graceful degradation.** The deterministic pipeline runs end-to-end without the agentic layer. An LLM outage never blocks a scheduled regulatory run.
12. **Minimum necessary data to the model.** Agents receive summaries, aggregates, and hashed identifiers, never raw PII and never more record-level data than the task needs. Outbound LLM traffic is scanned for PII.

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

### 4.1 Agentic Control Plane (v2.0)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ USERS: Data Engineering · Risk · Finance · Regulatory Reporting · Audit     │
│ Conversational workspace · Approval Queue · Scenario Comparison · Dashboard │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 7 — AGENT RUNTIME (supervisor + specialists, stateful graph)          │
│  AG-1 Pipeline Operations (supervisor)   AG-2 Data Quality Triage           │
│  AG-3 Stress Scenario                    AG-4 Executive Reporting           │
│  AG-5 Data Product Concierge                                                │
│  • Pinned model + versioned prompts   • Session state checkpointing          │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                ▼  every tool call
┌─────────────────────────────────────────────────────────────────────────────┐
│ POLICY ENFORCEMENT POINT (deterministic)                                    │
│  effective permission = user's RBAC ∩ agent allowlist                       │
│  decision: AUTONOMOUS | CONFIRM | PROPOSE | HUMAN_ONLY | PROHIBITED          │
│  PII egress guard · rate limits · full trace to audit log                   │
└──────────────┬────────────────────────────────────────┬─────────────────────┘
               ▼ allowed calls                           ▼ proposals
┌─────────────────────────────────────┐   ┌───────────────────────────────────┐
│ MCP TOOL SERVER                      │   │ APPROVAL QUEUE                    │
│ typed tools wrapping Layers 1–6 and  │   │ evidence · rationale · approver   │
│ the Stress Engine                    │   │ decision + reason logged          │
└──────────────┬──────────────────────┘   └───────────────────────────────────┘
               ▼
   Layers 1–6 (deterministic engine)  +  STRESS ENGINE (new, deterministic)
   Scenario Reference Store: Fed supervisory scenarios, translation tables

Cross-cutting (extended): Agent Trace Store · Numeric Grounding Checker · Evaluation Harness
```

The Stress Engine is a deterministic extension of Layer 4. It applies versioned scenario translation tables (macro variables → PD/LGD multipliers and drawdown assumptions) to governed loan data and recomputes EAD, EL, and RWA per projection quarter.

## 5. Requirement-to-Capability Mapping

### 5.1 Deterministic Engine (requirements §2)

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

### 5.2 Agentic Layer (requirements §3, v2.0)

| Requirement | Architectural Capability | Key Design Decisions |
|---|---|---|
| AG-1 Pipeline Operations Agent | Supervisor agent over C16 Orchestrator tools | Plan shown before execution; threshold checks after each stage; pauses and escalates instead of publishing on breach |
| AG-2 Data Quality Triage Agent | Specialist agent + quarantine summary tools | Reasons over deterministic group-by summaries and small hashed samples; output is proposals only |
| AG-3 Stress Scenario Agent | Specialist agent + `ScenarioSpec` validator + Stress Engine | NL → typed spec → user confirmation → deterministic run; ad-hoc shocks auto-labeled EXPLORATORY |
| AG-4 Executive Reporting Agent | Specialist agent + Numeric Grounding Checker | Narratives bind figures to tool-output fields; unbound numbers block release |
| AG-5 Data Product Concierge | Specialist agent + guarded SQL tool | Generated SQL parsed and allow-listed (SELECT over sandbox views only); runs with the user's permissions |
| 3.3 Tool catalog | MCP Tool Server | One typed tool per engine capability; no tool returns raw PII; re-identification not exposed |
| 3.4 Autonomy policy | Policy Enforcement Point + Approval Queue | Tool-level autonomy levels in versioned config; agents can never approve proposals |
| 3.5 Governance | Agent Trace Store, model inventory entry, Evaluation Harness | Pinned model and prompt versions; changes gated by evaluation results |
| 3.6 Agent UI | Conversational workspace + Approval Queue + Scenario Comparison views | Plans and tool calls visible to the user; rejections require a reason |

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
| **Agent Resilience** | Deterministic runs complete without the agentic layer; agent errors never leave a run in a partial published state. |
| **Agent Reproducibility** | Stressed metrics are identical for the same `ScenarioSpec`, reference versions, and engine version. Agent wording may vary; numbers may not. |
| **Agent Privacy** | No raw PII in prompts, agent state, traces, or LLM provider traffic, verified by automated scan of outbound payloads. |
| **Agent Explainability** | Every agent output links to its plan, tool calls, policy decisions, and source run IDs. |
| **Agent Latency & Cost** | Plan returned within ~10 seconds for interactive requests; token usage and cost logged per session. |

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

6. **Deterministic tools vs. letting the LLM calculate.**
   - *Decision*: All metrics, stressed or not, come from deterministic tools. The LLM never does arithmetic on regulatory figures.
   - *Trade-off*: Less flexible "quick answers"; every new type of analysis needs a tool. This is accepted because reproducibility and auditability are non-negotiable for FR Y-14/CCAR data.

7. **MCP server as the tool interface vs. framework-native function calls.**
   - *Decision*: Expose engine capabilities through a Model Context Protocol server.
   - *Trade-off*: One extra service to run, but tools become reusable across agent frameworks and clients, have explicit schemas, and form a single choke point for policy enforcement and logging.

8. **Supervisor + specialist agents vs. one general agent.**
   - *Decision*: A supervisor (AG-1) with four narrow specialists, each with a small tool allowlist.
   - *Trade-off*: More orchestration complexity, but each agent has a smaller blast radius, can be evaluated separately, and maps to a clear business owner.

9. **Deterministic policy layer vs. prompt-based guardrails.**
   - *Decision*: Autonomy limits live in versioned policy configuration enforced in code before every tool call.
   - *Trade-off*: Policy must be maintained alongside tools, but guardrails can't be bypassed by prompt injection or model drift.

10. **Confirmed `ScenarioSpec` vs. direct natural-language execution.**
    - *Decision*: Stress requests become a typed spec that the user confirms before anything runs; ambiguity triggers a clarifying question.
    - *Trade-off*: One extra interaction per request, in exchange for removing the main source of wrong-but-plausible stress results: a misread request.

11. **Simplified, transparent stress translation vs. production stress models.**
    - *Decision*: Use versioned linear sensitivity tables (macro variable → PD/LGD multiplier and drawdown uplift by segment) with a static balance sheet.
    - *Trade-off*: Results are illustrative, not CCAR-grade loss projections. The architecture allows the translation tool to be replaced by an approved model later without changing agents or interfaces.

## 8. Assumptions

- Source data (loan records, counterparty exposures, credit performance feeds) is synthetic and generated/mocked for this system; no live core-banking connection is required.
- "Event-driven ingestion" can be satisfied with a message-queue-based or file-watch-based simulation; a full enterprise streaming platform is not mandated.
- Regulatory parameter tables (CCFs, risk weights, PD/LGD grids) will be seeded with publicly documented standardized approach values (e.g., Basel III standardized risk weights) for demonstration purposes, clearly labeled as reference data subject to governance update.
- The FR Y-14Q/M/A "schedule" outputs are modeled as structurally representative aggregation outputs (period × segment × grade × maturity), not a byte-for-byte replica of the official FR Y-14 XML/XBRL submission templates — full regulatory submission formatting is a stretch goal, not a baseline requirement, unless specified otherwise.
- A single consolidated relational/analytical data store (e.g., a columnar or relational database) is acceptable for raw/cleansed/quarantine/aggregate zones, logically separated by schema/namespace rather than requiring separate physical platforms.

- Federal Reserve supervisory scenario variables (Baseline, Severely Adverse; 9-quarter horizon) are loaded from the publicly released scenario tables as versioned reference data.
- Scenario translation tables are illustrative, documented, and approved as reference data; they are not calibrated models.
- An enterprise-grade LLM endpoint is available with contractual no-training and data-retention controls; the model version can be pinned.
- Agents act on behalf of an authenticated user; scheduled runs use a service principal limited to running (not approving or publishing past a breach).

## 9. Out of Scope (for this phase)

- Integration with real/production core banking or regulatory submission systems.
- Full enterprise IAM/SSO integration (RBAC will be modeled and enforced in-application with a role table, not integrated with an external identity provider).
- Official FR Y-14 XBRL/XML submission packaging and electronic filing to the Federal Reserve's reporting portal.
- Disaster recovery / multi-region high availability.
- Model risk management (MRM) validation of the risk metric formulas beyond implementing the stated formulas correctly. (The agentic components are documented in a model inventory entry aligned with SR 11-7 principles, but independent validation is out of scope.)
- Production CCAR loss models, PPNR projections, balance sheet dynamics, and capital plan submission.
- Agents that change reference data, approve their own or other agents' proposals, or access raw PII.
- Fine-tuning or training models on bank data.

## 10. Success Criteria

- All five functional requirement areas (2.1–2.5) have a working, demonstrable implementation.
- A sample run ingests synthetic loan data, quarantines intentionally-bad records with correct reason codes, hashes PII fields, computes EAD/EL/RWA per loan, aggregates into schedule-shaped outputs, and renders catalog health metrics + a read-only query sandbox.
- All calculations are reproducible: re-running the same input snapshot through the same contract/parameter versions yields identical output.
- RBAC demonstrably restricts unmasked PII access to a designated compliance/audit role only.
- **Agentic (v2.0):** A natural-language run request produces a visible plan, runs through tools only, and pauses with an escalation when DQ falls below threshold.
- **Agentic (v2.0):** A natural-language stress request becomes a confirmed `ScenarioSpec`, produces baseline vs. stressed results that match hand-calculated fixtures, and can be replayed to identical numbers.
- **Agentic (v2.0):** No narrative is released with a figure that isn't bound to a tool output; no agent can apply a change without a recorded human approval; seeded prompt-injection records do not change agent behavior.
