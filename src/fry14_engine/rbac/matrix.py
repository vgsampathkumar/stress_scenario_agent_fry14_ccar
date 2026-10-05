"""Role -> permission matrix (C14). Static, versioned-in-code config. See
02-design-document.md §2.9 (base matrix) and §2.12 (v2.0 additions).

Agents (v2.0) never hold any `APPROVE_*` permission regardless of the
matrix below — that is enforced structurally by the Policy Enforcement
Point (C24, Phase 9): effective permission for a tool call is always
(requesting user's permissions) ∩ (agent's tool allowlist), and no agent's
allowlist is ever given an `APPROVE_*` tool. This matrix describes human
(and `SYSTEM_SCHEDULER` service-principal) permissions only.
"""

from __future__ import annotations

from fry14_engine.common.enums import Permission, RoleName

ROLE_PERMISSION_MATRIX: dict[RoleName, frozenset[Permission]] = {
    RoleName.DATA_ENGINEER: frozenset(
        {
            Permission.MANAGE_CONTRACTS,
            Permission.REMEDIATE_QUARANTINE,
            Permission.VIEW_CATALOG,
            Permission.RUN_PIPELINE,
            Permission.APPROVE_REMEDIATION,
            Permission.APPROVE_CONTRACT_CHANGE,
        }
    ),
    RoleName.FINANCE: frozenset(
        {
            Permission.QUERY_SANDBOX_READ,
            Permission.VIEW_CATALOG,
            Permission.RUN_STRESS_SCENARIO,
        }
    ),
    RoleName.RISK: frozenset(
        {
            Permission.QUERY_SANDBOX_READ,
            Permission.VIEW_CATALOG,
            Permission.MANAGE_REFERENCE_DATA,
            Permission.RUN_STRESS_SCENARIO,
            Permission.APPROVE_NARRATIVE,
            Permission.MANAGE_SCENARIO_TABLES,
        }
    ),
    RoleName.REGULATORY_REPORTING: frozenset(
        {
            Permission.QUERY_SANDBOX_READ,
            Permission.VIEW_CATALOG,
            Permission.PUBLISH_DATA_PRODUCT,
            Permission.APPROVE_NARRATIVE,
        }
    ),
    RoleName.COMPLIANCE_AUDIT: frozenset(
        {
            Permission.VIEW_RAW_PII,
            Permission.VIEW_HASHED_PII,
            Permission.QUERY_SANDBOX_READ,
            Permission.VIEW_CATALOG,
        }
    ),
    RoleName.SYSTEM_SCHEDULER: frozenset(
        {
            Permission.RUN_PIPELINE,
        }
    ),
    RoleName.ADMIN: frozenset(Permission),
}
