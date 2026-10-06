"""Shared enumerations used across ingestion, validation, and governance layers.

See 02-design-document.md §2 for the data model these enums participate in.
"""

from __future__ import annotations

from enum import StrEnum


class IngestionChannel(StrEnum):
    BATCH = "BATCH"
    EVENT = "EVENT"


class RemediationStatus(StrEnum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    WONT_FIX = "WONT_FIX"


class RuleSeverity(StrEnum):
    REJECT = "REJECT"
    WARN = "WARN"


class MaturityBucket(StrEnum):
    M_0_12 = "0-12M"
    M_13_36 = "13-36M"
    M_37_60 = "37-60M"
    M_60_PLUS = "60M+"


class SlaStatus(StrEnum):
    ON_TIME = "ON_TIME"
    AT_RISK = "AT_RISK"
    BREACHED = "BREACHED"


class RoleName(StrEnum):
    DATA_ENGINEER = "DATA_ENGINEER"
    FINANCE = "FINANCE"
    RISK = "RISK"
    REGULATORY_REPORTING = "REGULATORY_REPORTING"
    COMPLIANCE_AUDIT = "COMPLIANCE_AUDIT"
    ADMIN = "ADMIN"
    # v2.0: service principal for scheduled runs — can RUN_PIPELINE but never
    # APPROVE_* or PUBLISH_DATA_PRODUCT past a threshold breach. See
    # 02-design-document.md §2.12.
    SYSTEM_SCHEDULER = "SYSTEM_SCHEDULER"


class Permission(StrEnum):
    VIEW_AGGREGATE_DATA = "VIEW_AGGREGATE_DATA"
    VIEW_RAW_PII = "VIEW_RAW_PII"
    VIEW_HASHED_PII = "VIEW_HASHED_PII"
    MANAGE_CONTRACTS = "MANAGE_CONTRACTS"
    MANAGE_REFERENCE_DATA = "MANAGE_REFERENCE_DATA"
    QUERY_SANDBOX_READ = "QUERY_SANDBOX_READ"
    VIEW_CATALOG = "VIEW_CATALOG"
    REMEDIATE_QUARANTINE = "REMEDIATE_QUARANTINE"
    # v2.0 additions (02-design-document.md §2.12) — agents never hold any
    # APPROVE_* permission; effective permission for a tool call is always
    # (requesting user's permissions) ∩ (agent's tool allowlist).
    RUN_PIPELINE = "RUN_PIPELINE"
    PUBLISH_DATA_PRODUCT = "PUBLISH_DATA_PRODUCT"
    RUN_STRESS_SCENARIO = "RUN_STRESS_SCENARIO"
    APPROVE_REMEDIATION = "APPROVE_REMEDIATION"
    APPROVE_CONTRACT_CHANGE = "APPROVE_CONTRACT_CHANGE"
    APPROVE_NARRATIVE = "APPROVE_NARRATIVE"
    MANAGE_SCENARIO_TABLES = "MANAGE_SCENARIO_TABLES"


class AutonomyLevel(StrEnum):
    """Policy Enforcement Point (C24) decision for a tool call. Must stay in
    lockstep with the CHECK constraints on agent_governance.tool_policy.autonomy
    and .tool_policy_condition.escalate_to in schemas/013_agent_governance.sql.
    See 02-design-document.md §2.11, §3.14.
    """

    AUTONOMOUS = "AUTONOMOUS"
    CONFIRM = "CONFIRM"
    PROPOSE = "PROPOSE"
    HUMAN_ONLY = "HUMAN_ONLY"
    PROHIBITED = "PROHIBITED"


class AgentId(StrEnum):
    """The fixed agent roster (requirements.md §3.1). See
    02-design-document.md §1, C18-C22."""

    AG1_PIPELINE_OPERATIONS = "AG-1"
    AG2_DATA_QUALITY_TRIAGE = "AG-2"
    AG3_STRESS_SCENARIO = "AG-3"
    AG4_EXECUTIVE_REPORTING = "AG-4"
    AG5_DATA_PRODUCT_CONCIERGE = "AG-5"


class AuditEventType(StrEnum):
    """Lineage & Audit Log Service (C15) event categories — every stage of
    a pipeline run, plus access-control decisions. See
    02-design-document.md §3.10 and schemas/010_audit.sql."""

    INGESTION = "INGESTION"
    VALIDATION = "VALIDATION"
    PII_HASH = "PII_HASH"
    CALCULATION = "CALCULATION"
    AGGREGATION = "AGGREGATION"
    CATALOG_UPDATE = "CATALOG_UPDATE"
    ACCESS_CONTROL = "ACCESS_CONTROL"
    ORCHESTRATION = "ORCHESTRATION"
