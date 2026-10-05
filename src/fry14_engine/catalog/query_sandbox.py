"""Query Sandbox Service (C13): read-only, RBAC-scoped access to the
published schedule aggregates. See 02-design-document.md §3.8 and
requirement 2.5 ("Consumer Query Sandbox").

No raw SQL is accepted from callers — every query is a typed, parameterized
method, so there is no SQL-injection surface and structurally no way to
express a write. This is the Python-service-layer realization of "a
parameterized API", the design doc's documented alternative to a
SQL-over-views layer. RBAC is enforced here regardless of what permissions
the underlying DuckDB connection happens to have (defense in depth).
"""

from __future__ import annotations

import duckdb

from fry14_engine.aggregation.models import ScheduleAggregate
from fry14_engine.aggregation.store import AggregationStore
from fry14_engine.common.enums import Permission, RoleName
from fry14_engine.rbac.service import RbacService


class QuerySandboxService:
    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        rbac_service: RbacService | None = None,
    ) -> None:
        self._aggregation_store = AggregationStore(connection)
        self._rbac_service = rbac_service or RbacService()

    def query_schedule(
        self, role: RoleName, reporting_period: str, schema_version: str
    ) -> list[ScheduleAggregate]:
        """Raises `PermissionDeniedError` (fry14_engine.rbac.service) if
        `role` lacks `QUERY_SANDBOX_READ` — callers should let that
        propagate (or catch it) rather than pre-checking, so the denial is
        enforced in exactly one place."""
        self._rbac_service.require_permission(role, Permission.QUERY_SANDBOX_READ)
        return self._aggregation_store.read_by_reporting_period(reporting_period, schema_version)
