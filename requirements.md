# Use Case 1: Governed Agentic Data Product Orchestrator & Stress Scenario Agent (FR Y-14 / CCAR)

**Version:** 2.0 (agentic) · supersedes v1.0 "Governed Financial Data Product Engine"

## 1. Executive Functional Scope

The system automates ingestion, standardization, governance, and capital metric calculation for credit and wholesale loan portfolios. It produces regulatory data schedules for Federal Reserve capital stress testing (FR Y-14Q/M/A) and CCAR exercises.

Version 2.0 adds a **governed agentic layer** on top of the deterministic data product engine. AI agents operate the pipeline, triage data quality exceptions, translate natural-language stress requests into structured scenarios, and write executive summaries. Every number is still produced by deterministic, versioned, testable code.

### 1.1 Core Design Principle: Agents Orchestrate, Code Calculates

| Responsibility | Owned by |
|---|---|
| Interpreting requests, planning steps, choosing tools, explaining results | AI agents (LLM) |
| Validation, PII hashing, EAD/EL/RWA, stressed metrics, aggregation | Deterministic tools (versioned Python/SQL) |
| Approving contract changes, reference data changes, remediation rules, scenario runs used for reporting | Humans (role-based approval) |
| Enforcing permissions, autonomy limits, and audit logging | Deterministic policy layer (not an LLM) |

The deterministic pipeline (Sections 2.1–2.5) must run end-to-end **without** the agentic layer. Agents are an operating layer, not a dependency. If the LLM is unavailable, scheduled regulatory runs still complete.

---

## 2. Functional Requirements: Deterministic Data Product Engine (retained from v1.0)

These requirements are unchanged in substance. Each one is now also exposed as an agent tool (Section 3.3).

### 2.1 Raw Portfolio Ingestion & Metadata Staging
- **Multi-Source Ingestion:** Support batch and event-driven ingestion of synthetic commercial loan records, counterparty exposures, and credit performance feeds.
- **Operational Metadata Stamping:** Tag every incoming record with ingestion timestamp, source entity code, pipeline run identifier, and original system of record.

### 2.2 Data Contract Enforcement & Exception Handling
- **Contract Validation:** Validate records against versioned schema contracts specifying mandatory attributes, data types, allowable ranges (e.g., internal credit risk grades 1–10), and non-null constraints.
- **Automated Exception Isolation:** Isolate non-compliant records (e.g., negative commitment balances, missing credit scores) in a quarantine repository with exception reason codes. Processing of valid records continues uninterrupted.

### 2.3 Regulatory Privacy & PII Governance
- **PII Obfuscation:** Apply keyed one-way hashing (HMAC-SHA256) to borrower tax IDs (SSN/EIN), legal names, and addresses before any downstream processing.
- **Role-Based Access Control (RBAC):** Restrict unmasked PII to authorized Compliance/Audit personnel.

### 2.4 Capital & Credit Risk Metric Calculations
- **Exposure at Default (EAD):** Outstanding balance + unadvanced commitments × credit conversion factor (CCF).
- **Expected Loss (EL):** EL = PD × LGD × EAD.
- **Risk-Weighted Assets (RWA):** EAD × regulatory risk weight by asset class (e.g., CRE vs. C&I).
- **Schedule Aggregations:** Aggregate by reporting period (YYYY-MM), portfolio segment, credit grade, and remaining maturity bucket.

### 2.5 Data Product Catalog & Consumer Interface
- **Operational Dashboard:** Show health score, DQ pass/fail %, schema version history, and SLA status per data product.
- **Consumer Query Sandbox:** Read-only, RBAC-scoped self-service queries for Finance, Risk, and Regulatory Reporting.

---

## 3. Functional Requirements: Agentic Layer (new in v2.0)

### 3.1 Agent Roster

| ID | Agent | Purpose | Primary users |
|---|---|---|---|
| AG-1 | **Pipeline Operations Agent** (supervisor) | Plans and runs pipeline executions, monitors outcomes, coordinates other agents, reports run status | Data Engineering, Data Product Owner |
| AG-2 | **Data Quality Triage Agent** | Analyzes quarantined records, clusters exceptions, proposes root causes and remediation rules | Data Engineering, Data Stewards |
| AG-3 | **Stress Scenario Agent** | Converts natural-language stress requests into structured, validated scenario specifications and runs them through the deterministic stress engine | Risk, Finance, Capital Planning |
| AG-4 | **Executive Reporting Agent** | Writes run summaries and stress-result narratives in which every figure is traceable to a tool output | Senior Risk/Finance leadership |
| AG-5 | **Data Product Concierge Agent** | Answers consumer questions over the governed aggregates using read-only, role-scoped queries | Finance, Risk, Regulatory Reporting |

### 3.2 Agent Requirements

#### AG-1 Pipeline Operations Agent
- **AG-1.1** Accept a run request (e.g., "Run the March 2026 FR Y-14Q refresh for the commercial portfolio"), create an explicit execution plan, and display the plan before execution.
- **AG-1.2** Run the pipeline only through registered tools (Section 3.3). Direct database writes or arbitrary code execution are not allowed.
- **AG-1.3** After each stage, check outcomes against thresholds (e.g., DQ pass rate ≥ 98%, SLA window). If a threshold is breached, pause and escalate instead of continuing to publish.
- **AG-1.4** When the DQ breach exceeds the configured threshold, hand off quarantined records to AG-2 automatically.
- **AG-1.5** Produce a structured run report: records ingested, quarantined by reason code, metrics computed, aggregates published, SLA status, and the `pipeline_run_id`.

#### AG-2 Data Quality Triage Agent
- **AG-2.1** Group quarantined records by reason code, source system, and field pattern, and identify likely root causes (e.g., "84% of `MISSING_CREDIT_SCORE` exceptions come from one source feed after a schema change").
- **AG-2.2** Propose remediation as **draft artifacts only**: a candidate contract amendment, a data correction rule, or a ticket for the source system owner.
- **AG-2.3** Never modify quarantined records, contracts, or reference data directly. Every proposal goes to a human approval queue for `DATA_ENGINEER` (records/rules) or the contract owner (contract changes).
- **AG-2.4** After a remediation is approved, request a reprocessing run through AG-1. Reprocessed records keep lineage to their original quarantine IDs.
- **AG-2.5** Work only on hashed PII. Raw PII never enters an agent's context.

#### AG-3 Stress Scenario Agent
- **AG-3.1 Scenario intake:** Accept natural-language requests (e.g., "Run Severely Adverse on the CRE book with a 200 bps rate shock and show the change in EL and RWA").
- **AG-3.2 Structured translation:** Convert each request into a validated `ScenarioSpec` object specifying base scenario, portfolio scope, shocked variables, magnitudes, horizon, and reference-data versions. Show it to the user for confirmation **before** execution. Ambiguous requests trigger a clarifying question, not an assumption.
- **AG-3.3 Supported scenarios:**
  - Federal Reserve supervisory scenarios (Baseline, Severely Adverse), loaded as versioned reference data over a 9-quarter horizon.
  - User-defined ad-hoc shocks (e.g., rate shocks, CRE value declines, grade downgrades), labeled **"Exploratory – not for regulatory submission."**
- **AG-3.4 Deterministic stress engine:** Stressed metrics are computed only by a deterministic stress tool using versioned **scenario translation tables** that map macro variables to PD/LGD multipliers and CCF/drawdown assumptions by segment and grade. The agent never generates or adjusts PD, LGD, EAD, EL, or RWA values itself.
- **AG-3.5 Correct metric sensitivities:** The engine reflects that under the standardized approach, RWA changes through stressed **EAD** (e.g., commitment drawdowns) and balance changes, not through PD. EL changes through stressed PD, LGD, and EAD.
- **AG-3.6 Comparison output:** Return baseline vs. stressed results by segment, grade, and quarter, with deltas for EAD, EL, and RWA, plus the top contributing segments.
- **AG-3.7 Reproducibility:** Persist every scenario run with its `ScenarioSpec`, reference-data versions, calculation engine version, and model version, so the run can be replayed exactly.

#### AG-4 Executive Reporting Agent
- **AG-4.1** Write executive summaries of pipeline runs and stress results in business language.
- **AG-4.2 Numeric grounding:** Every number in a narrative must come from a tool output and cite its source (`pipeline_run_id` / `scenario_run_id`). A deterministic post-check compares narrative figures to tool outputs. Any mismatch blocks release.
- **AG-4.3** Clearly state limitations, data exceptions, and exploratory labels in every summary.
- **AG-4.4** Summaries are drafts until approved by a user with the `REGULATORY_REPORTING` or `RISK` role.

#### AG-5 Data Product Concierge Agent
- **AG-5.1** Answer natural-language questions over the governed aggregates by generating queries through the read-only sandbox tool.
- **AG-5.2** Inherit the **requesting user's** RBAC permissions. The agent has no permissions of its own beyond the user's.
- **AG-5.3** Show the generated query alongside the answer for transparency.
- **AG-5.4** Refuse requests for raw PII or write operations, and log the refusal.

### 3.3 Agent Tool Catalog (exposed via MCP server)

Deterministic engine capabilities are exposed as typed tools through a Model Context Protocol (MCP) server. Each tool has an input schema, an output schema, a required permission, and an autonomy level.

| Tool | Wraps | Permission | Autonomy |
|---|---|---|---|
| `ingest_batch` / `ingest_event` | 2.1 | `RUN_PIPELINE` | Autonomous |
| `validate_against_contract` | 2.2 | `RUN_PIPELINE` | Autonomous |
| `get_quarantine_summary` | 2.2 | `REMEDIATE_QUARANTINE` (read) | Autonomous |
| `propose_remediation` | 2.2 | `REMEDIATE_QUARANTINE` | Draft → human approval |
| `apply_remediation` | 2.2 | `REMEDIATE_QUARANTINE` | Human-only |
| `propose_contract_change` | 2.2 | `MANAGE_CONTRACTS` | Draft → human approval |
| `calculate_risk_metrics` | 2.4 | `RUN_PIPELINE` | Autonomous |
| `aggregate_schedules` | 2.4 | `RUN_PIPELINE` | Autonomous |
| `publish_data_product` | 2.5 | `PUBLISH_DATA_PRODUCT` | Human approval if any threshold breached |
| `build_scenario_spec` | AG-3 | `RUN_STRESS_SCENARIO` | Autonomous (validation only) |
| `run_stress_scenario` | AG-3 | `RUN_STRESS_SCENARIO` | Requires user confirmation of spec |
| `query_sandbox` | 2.5 | `QUERY_SANDBOX_READ` | Autonomous, read-only |
| `get_catalog_status` | 2.5 | `VIEW_CATALOG` | Autonomous |
| `get_lineage` | Cross-cutting | `VIEW_CATALOG` | Autonomous |

No tool returns raw PII. The re-identification capability (v1.0 §2.3) is **not** exposed to agents.

### 3.4 Autonomy & Human-in-the-Loop Policy

| Level | Actions | Control |
|---|---|---|
| **Autonomous** | Read, validate, calculate, aggregate, summarize, query | Logged |
| **Propose → Approve** | Remediation rules, contract amendments, publishing after a threshold breach, release of executive summaries | Approval queue with named approver and reason |
| **Human-only** | Reference data changes (CCF, risk weights, scenario translation tables), applying remediation, re-identification of PII | Not callable by agents |
| **Prohibited** | Raw PII access, direct DB writes, arbitrary code execution, generating or overriding numeric metrics | Blocked by the policy layer |

Autonomy limits are enforced by a deterministic policy layer between agents and tools, not by prompt instructions.

### 3.5 Agent Governance, Audit & Model Risk

- **AG-GOV-1 Agent audit trail:** Log every agent step: user request, plan, tool calls with inputs and outputs, approvals, model name and version, prompt template version, and final response. Link each entry to the `pipeline_run_id` / `scenario_run_id` in the lineage service.
- **AG-GOV-2 Model & prompt versioning:** Pin LLM model versions and version prompt templates in source control. Changing either requires re-running the evaluation suite (AG-GOV-4).
- **AG-GOV-3 Model inventory:** Register the agentic components in a model inventory entry with documented purpose, limitations, and controls, aligned with SR 11-7 model risk management principles.
- **AG-GOV-4 Evaluation suite:** Maintain automated evaluations covering:
  - Scenario translation accuracy: a golden set of natural-language requests with expected `ScenarioSpec` outputs.
  - Triage accuracy: root-cause identification on seeded defects from the synthetic data generator.
  - Narrative numeric fidelity: 100% of figures must match tool outputs.
  - Guardrail tests: attempted PII access, write operations, and out-of-scope requests must all be refused.
- **AG-GOV-5 Prompt injection resilience:** Treat data content (record fields, file contents, quarantine payloads) as data, never as instructions. Test this with seeded adversarial records.

### 3.6 Agent User Interface

- **AG-UI-1** Provide a conversational workspace where users interact with the agents, alongside the existing Operational Dashboard.
- **AG-UI-2** Show the agent's plan, the tool calls in progress, and the results, so users can see what the agent is doing.
- **AG-UI-3** Provide an **Approval Queue** view listing pending proposals with their rationale, evidence, and approve/reject controls (rejections require a reason, which is logged).
- **AG-UI-4** Provide a **Scenario Comparison** view (baseline vs. stressed by segment, grade, and quarter).

---

## 4. Non-Functional Requirements (agentic additions)

| Category | Requirement |
|---|---|
| Resilience | Deterministic pipeline runs complete without the agentic layer; agent failure never blocks scheduled regulatory runs |
| Reproducibility | Same `ScenarioSpec` + same reference versions + same engine version → identical stressed metrics |
| Privacy | No raw PII in prompts, agent context, logs, or LLM provider traffic (verified by automated scan) |
| Latency | Interactive agent responses return a plan within ~10 seconds; long runs stream progress |
| Cost visibility | Token usage and cost are logged per agent run |
| Explainability | Every agent output links to its plan, tool calls, and source run IDs |

---

## 5. Acceptance Criteria (agentic layer)

| Requirement | Acceptance Criterion |
|---|---|
| AG-1 | A natural-language run request produces a visible plan, runs end-to-end through tools only, and pauses with an escalation when DQ falls below threshold |
| AG-2 | On seeded defects, the agent identifies the correct source and root cause for at least 90% of exception clusters; no data is changed without recorded approval |
| AG-3 | At least 95% of golden-set requests produce the expected `ScenarioSpec`; ambiguous requests trigger clarification; stressed results match hand-calculated fixtures exactly |
| AG-3.5 | Tests confirm PD shocks change EL but not standardized RWA, and drawdown/CCF shocks change EAD and RWA |
| AG-4 | The numeric grounding check blocks any narrative containing a figure that is missing from tool outputs |
| AG-5 | Concierge answers match direct sandbox queries; non-permitted roles are denied; write/PII requests are refused and logged |
| 3.4 | Agents cannot call human-only or prohibited actions; attempts are blocked and logged by the policy layer |
| AG-GOV-1 | Any agent session can be fully reconstructed from audit logs |
| AG-GOV-5 | Seeded prompt-injection records do not change agent behavior |

---

## 6. Out of Scope

- Production CCAR loss models, PPNR projections, or capital plan submission. Stress outputs are illustrative and based on simplified, documented translation tables.
- Official FR Y-14 XBRL/XML filing.
- Agents that change reference data, approve their own proposals, or access raw PII.
- Integration with real core-banking systems or an enterprise identity provider (RBAC remains in-application).
