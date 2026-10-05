# Design Document: Governed Financial Data Product Engine (FR Y-14 / CCAR)

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

---

## 7. Security & Compliance Controls Summary

- No raw PII persisted beyond the transient ingestion buffer (hashed before any store write).
- Hashing key managed via secrets manager; rotated per a defined key-rotation policy (out of scope for this phase to automate, but design accommodates it — hash versioning field reserved).
- All PII re-identification access requires `VIEW_RAW_PII` and is logged with requester identity, timestamp, and justification reference.
- RBAC enforced at API/service layer (not solely DB grants) so the Query Sandbox cannot be bypassed to reach raw stores.
- Full lineage from source record to published schedule figure, satisfying regulatory traceability expectations.

---

## 8. Technology Considerations (non-binding, to be finalized in implementation plan)

- Storage: a single relational or analytical store (e.g., PostgreSQL or DuckDB/Parquet-on-disk) with logical schemas per zone (landing, quarantine, governed, metrics, aggregates, catalog, audit) is sufficient for the synthetic-data scale targeted here.
- Processing: can be implemented as a set of composable batch jobs/scripts (e.g., Python with pandas/Polars or SQL-based transformations) orchestrated by a lightweight scheduler, rather than requiring a full distributed compute platform.
- API/UI: a minimal web API + simple dashboard UI is sufficient to demonstrate catalog and sandbox capabilities.

Final technology choices are made in `03-implementation-plan.md` based on team skillset and delivery constraints.
