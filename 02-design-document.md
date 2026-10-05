# Design Document: Governed Agentic Data Product Orchestrator & Stress Scenario Agent (FR Y-14 / CCAR)

**Version 2.0 (agentic)** · Components C1–C16 are unchanged from v1.0. Components C17–C31 and the sections marked *(v2.0)* add the agentic layer and the stress engine.

Companion to `01-approach-paper.md` (architecture rationale) and `03-implementation-plan.md` (delivery plan). This document specifies components, data models, interfaces, and algorithms in enough detail to implement directly.

---

## 1. System Component Inventory

| # | Component | Responsibility |
|---|---|---|
| C1 | **Ingestion Gateway** | Batch + event-driven intake, format normalization |
| C2 | **Metadata Stamper** | Attaches operational metadata envelope to every record |
| C3 | **Landing Store** | Immutable, append-only raw zone |
| C4 | **Contract Registry** | Stores versioned data contracts (schema + business rules) |
| C5 | **Validation Engine** | Applies contract rules; routes valid/invalid |
| C6 | **Quarantine Store** | Holds rejected records with reason codes + remediation state |
| C7 | **PII Detection & Hashing Service** | Identifies and one-way-hashes PII fields |
| C8 | **Re-identification Vault** (restricted) | Optional reversible lookup, Compliance/Audit-only |
| C9 | **Reference Data Store** | PD/LGD grids, CCF table, risk-weight table, asset classification map |
| C10 | **Risk Metric Engine** | EAD / EL / RWA calculators |
| C11 | **Aggregation Engine** | Groups computed metrics into schedule structures |
| C12 | **Data Product Catalog Service** | Health score, DQ %, schema version history, SLA status |
| C13 | **Query Sandbox Service** | RBAC-scoped read-only query interface over aggregates |
| C14 | **RBAC / IAM Module** | Role-permission matrix, access enforcement |
| C15 | **Lineage & Audit Log Service** | Cross-cutting: records every transformation + access event |
| C16 | **Orchestrator** | Pipeline run scheduling, retry, idempotency control |
| C17 | **Agent Runtime** *(v2.0)* | Stateful supervisor/specialist graph, session checkpointing, model + prompt version pinning |
| C18 | **AG-1 Pipeline Operations Agent** *(v2.0)* | Plans and runs pipeline executions via tools, checks thresholds, escalates, coordinates specialists |
| C19 | **AG-2 Data Quality Triage Agent** *(v2.0)* | Clusters quarantine exceptions, infers root cause, drafts remediation proposals |
| C20 | **AG-3 Stress Scenario Agent** *(v2.0)* | Natural language → `ScenarioSpec`, confirmation, stress run, result interpretation |
| C21 | **AG-4 Executive Reporting Agent** *(v2.0)* | Grounded narratives for runs and scenarios |
| C22 | **AG-5 Data Product Concierge Agent** *(v2.0)* | Natural-language questions → guarded read-only queries |
| C23 | **MCP Tool Server** *(v2.0)* | Typed tool interface over C1–C16, C27, C28 |
| C24 | **Policy Enforcement Point (PEP)** *(v2.0)* | Allow / confirm / propose / deny decision on every tool call |
| C25 | **Approval Queue Service** *(v2.0)* | Stores agent proposals, routes to approvers, records decisions |
| C26 | **Agent Trace Store** *(v2.0)* | Extends C15 with agent sessions, plans, tool calls, policy decisions, model metadata |
| C27 | **Scenario Reference Store** *(v2.0)* | Fed supervisory scenarios, scenario translation tables, grade PD grid (versioned, approval-gated) |
| C28 | **Stress Engine** *(v2.0)* | Deterministic stressed PD/LGD/CCF → EAD/EL/RWA per loan per quarter |
| C29 | **Numeric Grounding Checker** *(v2.0)* | Verifies every figure in a narrative is bound to a tool output |
| C30 | **Evaluation Harness** *(v2.0)* | Golden-set, triage, grounding, and guardrail evaluations; release gate for model/prompt changes |
| C31 | **PII Egress Guard** *(v2.0)* | Scans every outbound LLM payload for PII patterns and blocks on detection |

---

## 2. Data Model

### 2.1 Canonical Loan Record (post-ingestion, pre-contract-validation)

```
RawLoanRecord {
  loan_id: string                      // source system loan identifier
  borrower_tax_id: string               // SSN/EIN — RAW, PII
  borrower_legal_name: string           // RAW, PII
  borrower_address: string              // RAW, PII
  counterparty_id: string
  asset_class: string                   // e.g. "CRE", "C&I"
  internal_credit_risk_grade: int       // 1–10
  credit_score: int | null
  outstanding_balance: decimal
  unadvanced_commitment: decimal
  origination_date: date
  maturity_date: date
  probability_of_default: decimal       // PD, 0–1
  loss_given_default: decimal           // LGD, 0–1
  portfolio_segment: string
  source_system_of_record: string
  _ingestion_metadata: IngestionMetadata
}

IngestionMetadata {
  ingestion_timestamp: timestamp (UTC)
  source_entity_code: string
  pipeline_run_id: uuid
  source_system_of_record: string
  ingestion_channel: enum { BATCH, EVENT }
}
```

### 2.2 Data Contract (versioned)

```
DataContract {
  contract_id: string
  version: semver                       // e.g. "1.2.0"
  effective_date: date
  fields: [
    {
      field_name: string
      data_type: enum { STRING, INT, DECIMAL, DATE, BOOLEAN }
      nullable: boolean
      allowed_range: { min, max } | null
      allowed_values: [string] | null     // enum constraint
      pii: boolean
    }, ...
  ]
  business_rules: [
    { rule_id, description, expression, severity: enum{REJECT, WARN} }
  ]
}
```

Example constraints driven by requirements:
- `internal_credit_risk_grade`: INT, range 1–10, non-null.
- `outstanding_balance`: DECIMAL, must be >= 0 (negative → reject, reason `NEGATIVE_BALANCE`).
- `credit_score`: INT, non-null required for scored products (missing → reject, reason `MISSING_CREDIT_SCORE`).

### 2.3 Quarantine Record

```
QuarantineRecord {
  quarantine_id: uuid
  original_record: RawLoanRecord (PII fields pre-hashed before storage)
  pipeline_run_id: uuid
  contract_id, contract_version: string
  rejected_at: timestamp
  exception_reason_codes: [string]       // e.g. ["NEGATIVE_BALANCE", "MISSING_CREDIT_SCORE"]
  remediation_status: enum { OPEN, IN_REVIEW, RESOLVED, WONT_FIX }
}
```

> **Note on PII in quarantine**: Even rejected records must not retain raw PII at rest. PII hashing (C7) runs *before* routing to quarantine or validated flow, so both branches only ever persist hashed PII. See §4.

### 2.4 Cleansed / Governed Loan Record (post-PII-hash, pre-risk-calc)

```
GovernedLoanRecord {
  loan_id: string
  borrower_key_hash: string              // HMAC-SHA256(borrower_tax_id)
  borrower_name_hash: string
  borrower_address_hash: string
  counterparty_id: string
  asset_class: string
  internal_credit_risk_grade: int
  credit_score: int
  outstanding_balance: decimal
  unadvanced_commitment: decimal
  maturity_date: date
  probability_of_default: decimal
  loss_given_default: decimal
  portfolio_segment: string
  _ingestion_metadata: IngestionMetadata
  _contract_version: semver
}
```

### 2.5 Reference Data

```
CreditConversionFactorTable { asset_class, commitment_type -> ccf: decimal (0–1) }
RiskWeightTable { asset_class -> risk_weight: decimal }          // e.g. CRE=1.00, C&I=1.00 (standardized, configurable)
RegulatoryParameterSet { version, effective_date, ccf_table, risk_weight_table }
```

### 2.6 Computed Metric Record

```
LoanRiskMetrics {
  loan_id: string
  reporting_period: string               // YYYY-MM
  EAD: decimal
  EL: decimal
  RWA: decimal
  asset_class: string
  portfolio_segment: string
  credit_rating_grade: int
  remaining_maturity_bucket: enum { "0-12M", "13-36M", "37-60M", "60M+" }
  calc_engine_version: semver
  regulatory_parameter_version: semver
}
```

### 2.7 Schedule Aggregate (final data product)

```
ScheduleAggregate {
  reporting_period: string               // YYYY-MM
  portfolio_segment: string
  credit_rating_grade: int
  remaining_maturity_bucket: string
  total_EAD: decimal
  total_EL: decimal
  total_RWA: decimal
  loan_count: int
  schema_version: semver
  generated_at: timestamp
}
```

### 2.8 Catalog Metadata

```
DataProductCatalogEntry {
  data_product_id: string                 // e.g. "fry14q.schedule.h1"
  health_score: decimal (0–100)
  dq_pass_percentage: decimal
  schema_version_history: [ { version, effective_date, changelog } ]
  sla_status: enum { ON_TIME, AT_RISK, BREACHED }
  last_run_id: uuid
  last_updated_at: timestamp
  owner: string
}
```

### 2.9 RBAC Model

```
Role { role_id, name: enum { DATA_ENGINEER, FINANCE, RISK, REGULATORY_REPORTING, COMPLIANCE_AUDIT, ADMIN } }

Permission {
  VIEW_AGGREGATE_DATA
  VIEW_RAW_PII            // Compliance/Audit only
  VIEW_HASHED_PII
  MANAGE_CONTRACTS
  MANAGE_REFERENCE_DATA
  QUERY_SANDBOX_READ
  VIEW_CATALOG
  REMEDIATE_QUARANTINE
}

RolePermissionMatrix:
  DATA_ENGINEER        -> MANAGE_CONTRACTS, REMEDIATE_QUARANTINE, VIEW_CATALOG
  FINANCE               -> QUERY_SANDBOX_READ, VIEW_CATALOG
  RISK                  -> QUERY_SANDBOX_READ, VIEW_CATALOG, MANAGE_REFERENCE_DATA(read)
  REGULATORY_REPORTING  -> QUERY_SANDBOX_READ, VIEW_CATALOG
  COMPLIANCE_AUDIT       -> VIEW_RAW_PII, VIEW_HASHED_PII, QUERY_SANDBOX_READ, VIEW_CATALOG
  ADMIN                  -> all
```

### 2.10 Stress Scenario Models *(v2.0)*

```
MacroVariable enum {
  UNEMPLOYMENT_RATE, REAL_GDP_GROWTH, CRE_PRICE_INDEX, HOUSE_PRICE_INDEX,
  TREASURY_3M, TREASURY_10Y, BBB_CORPORATE_YIELD
}

SupervisoryScenario {                     // loaded from public Fed scenario release
  scenario_version: string                // e.g. "FED-2026"
  scenario_name: enum { BASELINE, SEVERELY_ADVERSE }
  quarter: int                            // 0 = jump-off, 1..9 = projection quarters
  variables: map<MacroVariable, decimal>
}

ScenarioTranslationTable {               // illustrative, approval-gated reference data
  version: semver
  effective_date: date
  status: enum { DRAFT, APPROVED }
  approved_by: user_id | null
  entries: [
    {
      portfolio_segment: string
      asset_class: string
      target: enum { PD, LGD, DRAWDOWN }
      variable: MacroVariable
      beta: decimal                       // sensitivity per unit change
      transform: enum { LEVEL_CHANGE, PCT_CHANGE }
    }, ...
  ]
  grade_sensitivity: map<int, decimal>    // grade 1..10 -> PD scaling of shocks
  multiplier_floor: decimal               // e.g. 0.5
  multiplier_cap: decimal                 // e.g. 5.0
}

GradePDGrid { version, grade -> pd }      // used only for grade-migration shocks

ScenarioSpec {
  scenario_spec_id: uuid
  source_request_text: string             // user's original wording
  base_scenario: enum { BASELINE, SEVERELY_ADVERSE, NONE }
  supervisory_scenario_version: string | null
  portfolio_scope: {
    reporting_period: string              // YYYY-MM of the governed base data
    portfolio_segments: [string] | null   // null = all
    asset_classes: [string] | null
    credit_grades: [int] | null
  }
  adhoc_shocks: [
    {
      variable: MacroVariable
      shock_type: enum { ADD_BPS, ADD_PCT_POINTS, PCT_CHANGE }
      magnitude: decimal
      quarters: [int]                     // subset of 1..horizon
    }
  ]
  grade_migration: { notches: int, segments: [string] | null } | null
  horizon_quarters: int                   // 1..9, default 9
  translation_table_version: semver
  regulatory_parameter_version: semver
  classification: enum { SUPERVISORY, EXPLORATORY }  // EXPLORATORY if any ad-hoc shock or migration
  status: enum { DRAFT, NEEDS_CLARIFICATION, CONFIRMED, EXECUTED, REJECTED }
  requested_by: user_id
  confirmed_by: user_id | null
  confirmed_at: timestamp | null
}

StressedLoanMetrics {
  scenario_run_id: uuid
  loan_id: string
  quarter: int
  pd_stressed, lgd_stressed, ccf_stressed: decimal
  EAD_stressed, EL_stressed, RWA_stressed: decimal
}

ScenarioRunResult {
  scenario_run_id: uuid
  scenario_spec_id: uuid
  base_pipeline_run_id: uuid              // governed data used as input
  input_hash: string                      // hash of spec + input snapshot + versions
  stress_engine_version, translation_table_version, regulatory_parameter_version: semver
  classification: enum { SUPERVISORY, EXPLORATORY }
  rows: [
    {
      quarter, portfolio_segment, credit_rating_grade,
      EAD_base, EAD_stressed, EL_base, EL_stressed, RWA_base, RWA_stressed,
      delta_EAD, delta_EL, delta_RWA, loan_count
    }
  ]
  projected_loss_9q: decimal              // illustrative, see §3.18
  created_at: timestamp
}
```

### 2.11 Agent Governance Models *(v2.0)*

```
ToolPolicy {                              // versioned config, enforced by C24
  tool_name: string
  required_permission: Permission
  autonomy: enum { AUTONOMOUS, CONFIRM, PROPOSE, HUMAN_ONLY, PROHIBITED }
  allowed_agents: [agent_id]
  conditions: [ { expression, escalate_to: autonomy } ]   // e.g. publish if dq_pass < 0.98 -> PROPOSE
  max_calls_per_session: int
}

AgentProposal {
  proposal_id: uuid
  proposing_agent: agent_id
  session_id: uuid
  type: enum { REMEDIATION_RULE, CONTRACT_AMENDMENT, PUBLISH_OVERRIDE, NARRATIVE_RELEASE, SOURCE_TICKET }
  payload: json                           // the drafted change, never applied
  evidence: [ref]                         // quarantine ids, query ids, run ids
  rationale: string
  required_permission: Permission
  requires_four_eyes: boolean             // approver must differ from requester
  status: enum { PENDING, APPROVED, REJECTED, EXPIRED }
  decided_by: user_id | null
  decision_reason: string | null
  created_at, decided_at: timestamp
}

AgentTraceEvent {
  event_id: uuid
  session_id: uuid
  agent_id: string
  on_behalf_of: user_id | "SYSTEM_SCHEDULER"
  event_type: enum { USER_REQUEST, PLAN, TOOL_CALL, TOOL_RESULT, POLICY_DECISION,
                     PROPOSAL, APPROVAL, RESPONSE, GROUNDING_CHECK, ERROR }
  payload_ref: string                     // pointer + hash; payloads are PII-free
  model_id: string                        // pinned model identifier
  prompt_template_version: semver
  tokens_in, tokens_out, latency_ms: int
  pipeline_run_id | scenario_run_id: uuid | null
  timestamp: timestamp
}

GroundedNarrative {
  narrative_id: uuid
  template_text: string                   // contains bindings like {{run:<id>.total_EL_delta}}
  bindings: [ { token, source_run_id, field_path, value } ]
  rendered_text: string
  grounding_status: enum { PASSED, FAILED }
  approval_status: enum { DRAFT, APPROVED, REJECTED }
}
```

### 2.12 RBAC Extensions *(v2.0)*

New permissions:

```
RUN_PIPELINE              // trigger runs via tools
PUBLISH_DATA_PRODUCT      // publish aggregates to the catalog
RUN_STRESS_SCENARIO       // confirm and run ScenarioSpecs
APPROVE_REMEDIATION       // approve agent remediation proposals
APPROVE_CONTRACT_CHANGE   // approve contract amendments (four-eyes)
APPROVE_NARRATIVE         // release executive summaries
MANAGE_SCENARIO_TABLES    // edit/approve translation tables (human-only, four-eyes)
```

Updated matrix (additions only):

```
DATA_ENGINEER         += RUN_PIPELINE, APPROVE_REMEDIATION, APPROVE_CONTRACT_CHANGE
RISK                  += RUN_STRESS_SCENARIO, APPROVE_NARRATIVE, MANAGE_SCENARIO_TABLES
FINANCE               += RUN_STRESS_SCENARIO
REGULATORY_REPORTING  += PUBLISH_DATA_PRODUCT, APPROVE_NARRATIVE
SYSTEM_SCHEDULER (service principal) -> RUN_PIPELINE only
ADMIN                 -> all
```

**Agent identity.** Agents have no standing permissions. For each tool call, effective permission = (requesting user's permissions) ∩ (agent's tool allowlist) ∩ (tool autonomy level). Agents can never hold any `APPROVE_*` permission.

---

## 3. Component Design Detail

### 3.1 Ingestion Gateway (C1) + Metadata Stamper (C2)

- Two adapters implementing a common `IngestionAdapter` interface:
  - `BatchFileAdapter`: polls/receives file drops (CSV/JSON/Parquet) representing commercial loan extracts.
  - `EventStreamAdapter`: consumes a message queue/topic (e.g., simulated via a lightweight broker or append log) for near-real-time counterparty exposure or credit performance updates.
- Both adapters normalize incoming payloads into `RawLoanRecord` shape, then pass through the **Metadata Stamper**, which injects `_ingestion_metadata` deterministically:
  - `pipeline_run_id` generated once per orchestrated run (C16) and threaded through all records in that run.
  - `ingestion_timestamp` = wall-clock UTC at stamping time.
  - `source_entity_code` / `source_system_of_record` supplied by adapter config per feed.
- Output is written to the **Landing Store** (C3) as immutable, append-only partitions keyed by `pipeline_run_id` and `ingestion_channel`. No updates/deletes — corrections are new records with new run IDs (audit-friendly).

### 3.2 Contract Registry (C4) + Validation Engine (C5)

- Contracts authored as declarative config (JSON/YAML) matching the `DataContract` schema in §2.2, stored with semantic versioning; the active contract version for a run is recorded in run metadata.
- Validation Engine evaluates, per record, in order:
  1. Type check per field.
  2. Non-null check per field (`nullable: false`).
  3. Range/enum check (`allowed_range`, `allowed_values`).
  4. Custom business rules (e.g., `outstanding_balance >= 0`).
- Each failing check contributes an **exception reason code** (not just pass/fail) — a record can fail multiple checks, and all reason codes are captured (not just the first).
- **Routing**: a record with zero reason codes → valid stream (continues to C7). A record with ≥1 reason code → quarantine stream (C7 for PII hash, then C6). Both routings happen per-record in the same pass — no batch-level short-circuiting, satisfying "pipeline processing must continue uninterrupted."
- DQ metrics (`pass_count / total_count`) are emitted per run to the Catalog Service (C12).

### 3.3 PII Detection & Hashing Service (C7)

- PII fields are identified by **contract annotation** (`pii: true` in `DataContract.fields`) rather than inferred by pattern-matching alone — deterministic and auditable. Pattern-based detection (regex for SSN/EIN formats) is used as a secondary validation/alerting check to catch PII leaking into unexpected fields.
- Hashing algorithm: **HMAC-SHA256** with a secret key managed outside application config (secrets manager / environment-injected key), applied to normalized field values (e.g., strip formatting from SSN before hashing to ensure consistent keys).
- This runs **before** the valid/invalid fork so both quarantine and governed records only ever contain hashed PII at rest.
- Hashing is **deterministic** (same input + same key → same hash) so `borrower_key_hash` can be used as a stable join key across periods without exposing identity.
- **Re-identification Vault (C8)**: optional, separate service that stores `hash -> encrypted(raw_value)` pairs, written at hash-time but readable only via a distinct API requiring `VIEW_RAW_PII` permission, with every access logged to C15. This keeps the main pipeline PII-free while still allowing lawful re-identification for Compliance/Audit.

### 3.4 Reference Data Store (C9)

- Holds versioned, approval-gated tables:
  - **CCF table**: unadvanced commitment credit conversion factor by asset class / commitment type (e.g., unconditionally cancellable = 0%, committed but unused C&I = 20–50%, per standardized approach conventions — configurable, not hardcoded).
  - **Risk weight table**: by asset classification (e.g., Commercial Real Estate vs. Commercial & Industrial), per standardized regulatory risk-weight categories.
  - **PD/LGD** may come directly from source loan data (as the requirements imply per-loan PD/LGD) or be supplemented by a grade-based PD grid if per-loan values are absent; design supports both via a fallback rule in the Risk Metric Engine.
- Each table has a `version` + `effective_date`; the Risk Metric Engine always records which reference version it used (`regulatory_parameter_version` in `LoanRiskMetrics`), enabling exact reproducibility.

### 3.5 Risk Metric Engine (C10)

Pure calculation functions, unit-testable in isolation:

```
EAD(loan) =
    loan.outstanding_balance
  + loan.unadvanced_commitment * CCF(loan.asset_class, commitment_type)

EL(loan, computed_EAD) =
    loan.probability_of_default * loan.loss_given_default * computed_EAD

RWA(loan, computed_EAD) =
    computed_EAD * RiskWeight(loan.asset_class)
```

- `remaining_maturity_bucket` derived from `maturity_date - reporting_period_end_date`:
  - `0–12M`, `13–36M`, `37–60M`, `60M+`
- Each output record stamped with `calc_engine_version` (semver of the deployed calculation code) and `regulatory_parameter_version` (from C9) — the two together make every number reproducible.
- Engine processes the full valid-record stream per run; failures in calculation (e.g., missing PD) are themselves routed to a **calculation exception** sub-queue (distinct reason codes), not silently defaulted, preserving the "never fail-stop" principle at this layer too.

### 3.6 Aggregation Engine (C11)

- Group-by pipeline over `LoanRiskMetrics`:
  - Dimensions: `reporting_period`, `portfolio_segment`, `credit_rating_grade`, `remaining_maturity_bucket`.
  - Measures: `SUM(EAD)`, `SUM(EL)`, `SUM(RWA)`, `COUNT(loan_id)`.
- Output persisted as `ScheduleAggregate` rows, schema-versioned, into the governed **Schedule Data Product** store — the artifact consumed by Layer 6.
- Supports re-aggregation (idempotent re-run) keyed by `(reporting_period, schema_version)` so a corrected run supersedes cleanly, with the prior version retained for audit (schema version history).

### 3.7 Data Product Catalog Service (C12)

- Computes/stores, per data product (e.g., per schedule or per pipeline stage):
  - **Health score**: composite of DQ pass %, SLA adherence, freshness.
  - **DQ pass/fail %**: `valid_records / total_records` from the latest run.
  - **Schema version history**: append-only log of contract/schema versions with effective dates and changelogs.
  - **SLA status**: `ON_TIME` / `AT_RISK` / `BREACHED` computed by comparing run completion time against a configured SLA window per data product.
- Exposes a read API consumed by an **Operational Dashboard** UI (or UI-equivalent report for this phase).

### 3.8 Query Sandbox Service (C13)

- Exposes **read-only** query access over `ScheduleAggregate` (and optionally `LoanRiskMetrics` at a masked/hashed level) to roles `FINANCE`, `RISK`, `REGULATORY_REPORTING`.
- No write operations; enforced at the API layer regardless of underlying store permissions (defense in depth).
- Query interface can be a constrained SQL-over-views layer or a parameterized API (`GET /sandbox/schedule?period=&segment=&grade=`), chosen in the implementation plan based on build complexity vs. value.

### 3.9 RBAC / IAM Module (C14)

- Simple role table + permission matrix (per §2.9), enforced as a decorator/middleware on every service endpoint.
- `VIEW_RAW_PII` is the only permission gating access to C8 (Re-identification Vault); all other roles interact exclusively with hashed identifiers.
- Every permission check emits an audit event to C15 regardless of allow/deny outcome.

### 3.10 Lineage & Audit Log Service (C15)

- Append-only event log capturing: ingestion events, validation outcomes (incl. reason codes), PII hash operations (not raw values), risk calculations (input/version refs, not full payload replication), aggregation runs, catalog updates, and all access-control decisions.
- Each event includes `pipeline_run_id` so a single run can be fully reconstructed end-to-end (ingestion → quarantine/valid split → hash → calc → aggregate → catalog).

### 3.11 Orchestrator (C16)

- Coordinates a run: generates `pipeline_run_id`, sequences C1→C2→C3→C5→C7→(C6|C10)→C11→C12, handles retries for transient failures, and guarantees idempotency (re-running the same source batch with the same run parameters does not double-count — enforced via upsert-by-natural-key or run supersession).

---

### 3.12 Agent Runtime (C17) *(v2.0)*

- Implemented as a stateful graph: AG-1 is the supervisor node; AG-2 to AG-5 are specialist nodes, each with its own system prompt, tool allowlist, and output schema.
- Session state (plan, intermediate results, pending confirmations) is checkpointed, so a session can pause for human confirmation or approval and resume without re-running completed steps.
- Model ID and prompt template versions are pinned in config and written to every trace event.
- Specialist outputs are typed (structured output validated against Pydantic schemas). Invalid output is retried once, then escalated as an error rather than passed on.
- Hard limits per session: maximum steps, maximum tool calls, maximum tokens. Hitting a limit ends the session with a partial report.

### 3.13 MCP Tool Server (C23) *(v2.0)*

- Each engine capability is one tool with a JSON input schema, JSON output schema, and description. Tool names and policies follow `requirements.md` §3.3.
- Tools are thin wrappers: they call existing service APIs (C1–C16) or C28 and contain no business logic of their own.
- Every tool call passes through the PEP (C24) before execution and writes `TOOL_CALL` / `TOOL_RESULT` events to C26.
- Outputs are size-bounded. Tools return summaries, aggregates, and IDs, with record-level samples capped (e.g., ≤ 20 hashed records) to limit the data sent to the model.
- `/pii/reidentify` and reference-data write APIs are deliberately **not** exposed as tools.

### 3.14 Policy Enforcement Point (C24) *(v2.0)*

Decision procedure for each tool call:

1. Resolve the requesting user (or `SYSTEM_SCHEDULER`) and the calling agent.
2. Load the active `ToolPolicy` for the tool. Deny if the agent isn't in `allowed_agents`.
3. Deny if the user lacks `required_permission` (log as `AGENT_POLICY_DENIED`).
4. Evaluate `conditions` (e.g., DQ pass rate, classification) to compute the effective autonomy level.
5. Act on the autonomy level:
   - `AUTONOMOUS` → execute.
   - `CONFIRM` → return a confirmation request to the user; execute only after explicit confirmation.
   - `PROPOSE` → create an `AgentProposal` in C25; do not execute.
   - `HUMAN_ONLY` / `PROHIBITED` → deny and log.
6. Check per-session call limits.
7. Write a `POLICY_DECISION` event to C26 in every case.

The PEP is plain code with unit tests for every policy rule; it never calls an LLM.

### 3.15 Approval Queue Service (C25) *(v2.0)*

- Stores `AgentProposal` records with evidence links and rationale.
- Routes each proposal to users holding the required `APPROVE_*` permission. If `requires_four_eyes`, the approver must differ from the user who requested the session.
- Approval executes the change through the normal service API under the **approver's** identity, not the agent's. The executed change links back to the `proposal_id`.
- Rejections require a reason. Proposals expire after a configurable period (e.g., 5 business days).

### 3.16 AG-1 Pipeline Operations Agent (C18) *(v2.0)*

- Input: run request (natural language or schedule trigger).
- Plan template: ingest → validate → calculate → aggregate → check thresholds → publish (or propose publish) → report.
- After `validate_against_contract`, compares the DQ pass rate to the catalog threshold (default 98%). Below threshold: hands off to AG-2, sets publish to `PROPOSE`, and escalates to the data product owner.
- Output: structured `RunReport` (counts by stage, quarantine by reason code, SLA status, `pipeline_run_id`), passed to AG-4 for narrative.

### 3.17 AG-2 Data Quality Triage Agent (C19) *(v2.0)*

- Calls `get_quarantine_summary`, a deterministic tool returning counts grouped by reason code × source system × source entity × ingestion window × null/value patterns per field, plus up to 20 hashed sample records per cluster.
- The LLM reasons over the summary to form root-cause hypotheses. Each hypothesis must cite the cluster statistics that support it.
- Produces `AgentProposal` objects of type `REMEDIATION_RULE`, `CONTRACT_AMENDMENT`, or `SOURCE_TICKET`. Never edits data.
- After approval, asks AG-1 to reprocess affected records. Reprocessed records carry `original_quarantine_id` in lineage.

### 3.18 AG-3 Stress Scenario Agent (C20) and Stress Engine (C28) *(v2.0)*

**Agent flow**

1. Parse the request into a draft `ScenarioSpec` using structured output.
2. Call `build_scenario_spec` (deterministic validator): checks variables, magnitudes against plausibility bounds, scope against available governed data, and table versions, and sets `classification`.
3. If required fields are missing or ambiguous (e.g., "rate shock" with no magnitude, unclear portfolio), set status `NEEDS_CLARIFICATION` and ask one question.
4. Present the spec in plain language and wait for user confirmation (`CONFIRM` autonomy).
5. Call `run_stress_scenario`; receive `ScenarioRunResult`.
6. Interpret results (top contributing segments, drivers) and hand off to AG-4 for a grounded narrative.

**Stress Engine algorithm** (deterministic, per loan *i*, quarter *q*):

```
Δx(v,q)   = scenario(v,q) − scenario(v,0)  + adhoc_shock(v,q)     // jump-off relative
S_PD(i,q) = Σ_v beta(seg_i, PD, v) × Δx(v,q)
m_PD      = clamp(1 + grade_sensitivity(grade_i) × S_PD, floor, cap)
m_LGD     = clamp(1 + Σ_v beta(seg_i, LGD, v) × Δx(v,q), floor, cap)
d         = clamp(Σ_v beta(seg_i, DRAWDOWN, v) × Δx(v,q), 0, 1 − CCF_i)

pd_s      = min(1, PD_i' × m_PD)        // PD_i' = grid PD after grade migration, else PD_i
lgd_s     = min(1, LGD_i × m_LGD)
ccf_s     = CCF_i + d
EAD_s     = outstanding_balance_i + unadvanced_commitment_i × ccf_s
EL_s      = pd_s × lgd_s × EAD_s
RWA_s     = EAD_s × RiskWeight(asset_class_i)                     // standardized: no PD term
```

- **Static balance sheet:** balances and the portfolio composition are held at the jump-off position for all quarters.
- **Illustrative projected loss:** `projected_loss_9q = Σ_q Σ_i EL_s(i,q) / 4`, treating EL as an annualized rate applied quarterly. Labeled illustrative in every output.
- **Metric sensitivity is by construction:** PD and LGD shocks change EL only; drawdown shocks change EAD, EL, and RWA. Unit tests assert this (requirements AG-3.5).
- Results are aggregated by quarter × segment × grade with baseline (unstressed metrics from C10 for the same `base_pipeline_run_id`) and deltas.
- `input_hash` covers the spec, input snapshot, and all versions, so identical inputs are detected and give identical outputs.

### 3.19 AG-4 Executive Reporting Agent (C21) and Numeric Grounding Checker (C29) *(v2.0)*

- AG-4 writes narratives as **templates with bindings** rather than free numbers, e.g., "Severely Adverse raises CRE expected loss by {{run:7f3a.delta_EL.CRE}} ({{run:7f3a.delta_EL_pct.CRE}})."
- C29 resolves each binding against stored tool outputs, formats the value, and renders the text.
- C29 then scans the rendered text for any numeric token not produced by a binding (excluding an allowlist such as dates, quarter labels, and regulation names). Any unbound number, or any binding that fails to resolve, sets `grounding_status = FAILED` and blocks release.
- Passed narratives are saved as `DRAFT` and released through the Approval Queue (`NARRATIVE_RELEASE`, permission `APPROVE_NARRATIVE`).
- Every narrative includes the classification label (e.g., "Exploratory – not for regulatory submission"), data exceptions, and limitations.

### 3.20 AG-5 Data Product Concierge Agent (C22) *(v2.0)*

- Generates SQL against a documented set of sandbox views (schema and column descriptions provided as tool context).
- `query_sandbox` parses the SQL with a SQL parser and rejects anything other than a single `SELECT` over allow-listed views; it adds a row limit and executes under the user's identity with C13's read-only enforcement.
- Returns the answer with the executed SQL. Requests for PII or writes are refused and logged.

### 3.21 Evaluation Harness (C30) and PII Egress Guard (C31) *(v2.0)*

**Evaluation sets**

| Set | Content | Pass bar |
|---|---|---|
| Scenario translation | ≥ 50 natural-language requests with expected `ScenarioSpec` (including ambiguous ones expecting clarification) | ≥ 95% exact match on spec fields |
| Triage | Synthetic batches with seeded, known root causes | ≥ 90% correct root cause + source |
| Grounding | Narratives from fixture runs | 100% bound figures; 0 unbound numbers released |
| Guardrails | Attempts at PII access, writes, approvals, out-of-scope tools | 100% denied and logged |
| Prompt injection | Records and files containing instruction-like text | No change in tool calls vs. clean baseline |

- The harness runs in CI. Any change to model ID, prompt template, tool schema, or policy config must pass all sets before release.
- **PII Egress Guard:** inspects every payload sent to the LLM endpoint with pattern detectors (SSN/EIN formats, name/address heuristics on unexpected fields). A detection blocks the call, logs `PII_EGRESS_BLOCKED`, and alerts. Traces store only PII-free payloads.

## 4. End-to-End Data Flow (Sequence)

1. **Ingest**: Batch file or event message arrives → `IngestionAdapter` normalizes → `MetadataStamper` stamps → written to Landing Store.
2. **Validate**: `ValidationEngine` loads active `DataContract` → evaluates each record → tags pass/fail + reason codes.
3. **Hash PII**: Regardless of pass/fail, PII fields are hashed by `PIIHashingService` before any further branching (ensures quarantine never stores raw PII).
4. **Route**: Passing records → governed stream; failing records → `QuarantineStore` with reason codes + remediation status `OPEN`.
5. **Calculate**: Governed records flow into `RiskMetricEngine`, which computes EAD → EL, RWA using current `ReferenceDataStore` version; outputs `LoanRiskMetrics`.
6. **Aggregate**: `AggregationEngine` groups `LoanRiskMetrics` into `ScheduleAggregate` rows by period/segment/grade/maturity bucket.
7. **Publish & Catalog**: Aggregates published as the governed data product; `CatalogService` updates health score, DQ %, SLA status, schema version history.
8. **Consume**: Finance/Risk/Regulatory Reporting query via `QuerySandboxService` (read-only, RBAC-scoped); Compliance/Audit may separately query `ReidentificationVault` if a legitimate need arises (fully audited).

---

### 4.1 Agentic Flows *(v2.0)*

**A. Scheduled run with a DQ breach**

1. `SYSTEM_SCHEDULER` triggers AG-1 → plan created and logged.
2. AG-1 calls ingest, validate, calculate, and aggregate tools (all `AUTONOMOUS`).
3. DQ pass rate is 95% (< 98%) → PEP escalates `publish_data_product` to `PROPOSE`.
4. AG-1 hands off to AG-2 → AG-2 calls `get_quarantine_summary` → finds 84% of `MISSING_CREDIT_SCORE` from one source feed after a schema version change → creates a `SOURCE_TICKET` and a `REMEDIATION_RULE` proposal.
5. AG-4 drafts a grounded run summary → C29 passes it → `NARRATIVE_RELEASE` proposal.
6. Data engineer approves the remediation → AG-1 reprocesses affected records → DQ 99.2% → publish proceeds (or the Regulatory Reporting approver releases it).

**B. Stress scenario request**

1. Risk user: "Run Severely Adverse on the CRE book with an extra 200 bps rate shock; show EL and RWA changes."
2. AG-3 drafts the spec → `build_scenario_spec` validates → classification `EXPLORATORY` (ad-hoc shock present).
3. AG-3 asks: "Apply the +200 bps to the 10-year Treasury, the BBB yield, or both, and in which quarters?" → user answers.
4. AG-3 shows the plain-language spec → user confirms → `run_stress_scenario` → `ScenarioRunResult`.
5. AG-3 interprets the result; AG-4 writes a grounded narrative noting that RWA moved only through drawdown assumptions.
6. Scenario Comparison view shows baseline vs. stressed by quarter, segment, and grade.

**C. Concierge question**

1. Finance user: "What was total RWA for C&I grades 7–10 last quarter?"
2. AG-5 generates SQL → `query_sandbox` validates and runs it under the user's identity → answer returned with SQL.

## 5. Interface Contracts (representative)

```
POST /ingestion/batch           (DATA_ENGINEER)       -> triggers batch ingest run
POST /ingestion/event           (system-to-system)     -> event-driven single-record ingest
GET  /contracts/{id}/versions   (DATA_ENGINEER, ADMIN)
POST /contracts                 (DATA_ENGINEER, ADMIN) -> publish new contract version
GET  /quarantine?run_id=        (DATA_ENGINEER)
POST /quarantine/{id}/remediate (DATA_ENGINEER)
GET  /catalog                   (all authenticated roles) -> catalog listing + health/DQ/SLA
GET  /sandbox/schedule          (FINANCE, RISK, REGULATORY_REPORTING) -> read-only query
GET  /pii/reidentify/{hash}     (COMPLIANCE_AUDIT only) -> raw value, fully audited
```

*(v2.0 additions)*

```
POST /agent/sessions                        (authenticated)  -> start agent session
POST /agent/sessions/{id}/messages          (session owner)  -> send message / confirmation
GET  /agent/sessions/{id}/trace             (session owner, COMPLIANCE_AUDIT, ADMIN)
GET  /approvals?status=PENDING              (holders of any APPROVE_* permission)
POST /approvals/{id}/decision               (required APPROVE_* permission; four-eyes enforced)
POST /scenarios/specs                       (RUN_STRESS_SCENARIO) -> validate draft spec
POST /scenarios/specs/{id}/confirm          (RUN_STRESS_SCENARIO)
POST /scenarios/specs/{id}/run              (RUN_STRESS_SCENARIO) -> ScenarioRunResult
GET  /scenarios/runs/{run_id}               (RISK, FINANCE, REGULATORY_REPORTING)
GET  /reference/scenario-tables/{version}   (RISK, ADMIN)
POST /reference/scenario-tables             (MANAGE_SCENARIO_TABLES, four-eyes; not exposed to agents)
     /mcp                                   (agent runtime only, service-authenticated)
```

---

## 6. Error / Exception Reason Code Catalog (initial set)

| Code | Trigger |
|---|---|
| `NEGATIVE_BALANCE` | `outstanding_balance < 0` |
| `MISSING_CREDIT_SCORE` | `credit_score` null where required |
| `INVALID_CREDIT_GRADE` | `internal_credit_risk_grade` outside 1–10 |
| `NULL_MANDATORY_FIELD` | any non-nullable field missing |
| `TYPE_MISMATCH` | field fails declared data type |
| `UNKNOWN_ASSET_CLASS` | asset class not present in classification/risk-weight table |
| `CALC_MISSING_PD_LGD` | PD or LGD unavailable for EL calculation |
| `SCENARIO_SPEC_INVALID` *(v2.0)* | Draft spec fails validation (unknown variable, out-of-bounds shock, unavailable scope) |
| `SCENARIO_TABLE_NOT_APPROVED` *(v2.0)* | Referenced translation table version is not `APPROVED` |
| `CALC_SCENARIO_VARIABLE_MISSING` *(v2.0)* | Scenario lacks a variable required by the translation table for a segment |
| `AGENT_POLICY_DENIED` *(v2.0)* | PEP denied a tool call |
| `NARRATIVE_GROUNDING_FAILED` *(v2.0)* | Unbound number or unresolved binding in a narrative |
| `PII_EGRESS_BLOCKED` *(v2.0)* | PII detected in an outbound LLM payload |
| `AGENT_LIMIT_EXCEEDED` *(v2.0)* | Session hit step, tool-call, or token limit |

---

## 7. Security & Compliance Controls Summary

- No raw PII persisted beyond the transient ingestion buffer (hashed before any store write).
- Hashing key managed via secrets manager; rotated per a defined key-rotation policy (out of scope for this phase to automate, but design accommodates it — hash versioning field reserved).
- All PII re-identification access requires `VIEW_RAW_PII` and is logged with requester identity, timestamp, and justification reference.
- RBAC enforced at API/service layer (not solely DB grants) so the Query Sandbox cannot be bypassed to reach raw stores.
- Full lineage from source record to published schedule figure, satisfying regulatory traceability expectations.
- *(v2.0)* Agents have no standing permissions; every tool call is evaluated by the PEP against the user's RBAC, the agent allowlist, and the tool's autonomy level.
- *(v2.0)* Agents cannot approve proposals, change reference data, or reach re-identification. Approved changes execute under the approver's identity.
- *(v2.0)* Data in records, files, and tool outputs is treated as data, never as instructions. Tool outputs are passed to the model inside clearly delimited data blocks, and prompt-injection tests are part of the release gate.
- *(v2.0)* No raw PII in prompts, agent state, or traces; the PII Egress Guard blocks outbound payloads on detection.
- *(v2.0)* Every agent session is reconstructable from C26: request, plan, tool calls, policy decisions, approvals, model and prompt versions, output.
- *(v2.0)* Agentic components are documented in a model inventory entry (purpose, limitations, controls, evaluation results), aligned with SR 11-7 principles.

---

## 8. Technology Considerations (non-binding, to be finalized in implementation plan)

- Storage: a single relational or analytical store (e.g., PostgreSQL or DuckDB/Parquet-on-disk) with logical schemas per zone (landing, quarantine, governed, metrics, aggregates, catalog, audit) is sufficient for the synthetic-data scale targeted here.
- Processing: can be implemented as a set of composable batch jobs/scripts (e.g., Python with pandas/Polars or SQL-based transformations) orchestrated by a lightweight scheduler, rather than requiring a full distributed compute platform.
- API/UI: a minimal web API + simple dashboard UI is sufficient to demonstrate catalog and sandbox capabilities.

Final technology choices are made in `03-implementation-plan.md` based on team skillset and delivery constraints.

### 8.1 Agentic Layer Technology *(v2.0)*

- Agent runtime: a graph-based agent framework with state checkpointing (e.g., LangGraph) or the Claude Agent SDK.
- Tool interface: an MCP server built with the MCP Python SDK (FastMCP), wrapping the FastAPI services.
- Model: a pinned frontier model through an enterprise endpoint with no-training and retention controls (e.g., Claude via the Anthropic API or Amazon Bedrock).
- SQL guard: a SQL parser (e.g., sqlglot) for AG-5 query validation.
- Tracing: OpenTelemetry spans plus a self-hostable LLM trace viewer (e.g., Langfuse), with C26 remaining the system of record.
- Validation: Pydantic models for all agent outputs and tool schemas.
