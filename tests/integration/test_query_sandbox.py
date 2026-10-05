from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from fry14_engine.aggregation.models import ScheduleAggregate
from fry14_engine.aggregation.store import AggregationStore
from fry14_engine.catalog.query_sandbox import QuerySandboxService
from fry14_engine.common.enums import MaturityBucket, RoleName
from fry14_engine.db import bootstrap, get_connection
from fry14_engine.rbac.service import PermissionDeniedError

PERMITTED_ROLES = [RoleName.FINANCE, RoleName.RISK, RoleName.REGULATORY_REPORTING, RoleName.ADMIN]
DENIED_ROLES = [RoleName.DATA_ENGINEER, RoleName.SYSTEM_SCHEDULER]


@pytest.fixture
def seeded_db(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    AggregationStore(con).upsert(
        [
            ScheduleAggregate(
                reporting_period="2026-06",
                portfolio_segment="MIDDLE_MARKET",
                credit_rating_grade=5,
                remaining_maturity_bucket=MaturityBucket.M_13_36,
                total_ead="1000000.00",
                total_el="9000.00",
                total_rwa="1000000.00",
                loan_count=3,
                schema_version="1.0.0",
                pipeline_run_id="run-1",
            )
        ]
    )
    yield con
    con.close()


@pytest.mark.parametrize("role", PERMITTED_ROLES)
def test_permitted_roles_can_query(seeded_db, role):
    service = QuerySandboxService(seeded_db)
    rows = service.query_schedule(role, "2026-06", "1.0.0")
    assert len(rows) == 1
    assert rows[0].loan_count == 3


@pytest.mark.parametrize("role", DENIED_ROLES)
def test_non_permitted_roles_are_denied(seeded_db, role):
    service = QuerySandboxService(seeded_db)
    with pytest.raises(PermissionDeniedError):
        service.query_schedule(role, "2026-06", "1.0.0")


def test_denial_is_logged_with_role_and_permission(seeded_db):
    service = QuerySandboxService(seeded_db)
    with pytest.raises(PermissionDeniedError) as exc_info:
        service.query_schedule(RoleName.DATA_ENGINEER, "2026-06", "1.0.0")
    assert exc_info.value.role == RoleName.DATA_ENGINEER
    from fry14_engine.common.enums import Permission

    assert exc_info.value.permission == Permission.QUERY_SANDBOX_READ


def test_results_match_direct_store_query(seeded_db):
    service = QuerySandboxService(seeded_db)
    sandbox_rows = service.query_schedule(RoleName.FINANCE, "2026-06", "1.0.0")
    direct_rows = AggregationStore(seeded_db).read_by_reporting_period("2026-06", "1.0.0")
    assert sandbox_rows == direct_rows


def test_query_for_nonexistent_period_returns_empty_not_error(seeded_db):
    service = QuerySandboxService(seeded_db)
    rows = service.query_schedule(RoleName.FINANCE, "2099-01", "1.0.0")
    assert rows == []


def test_service_exposes_no_write_methods():
    """Structural guarantee, not just a behavioral test: there is no method
    on this class whose name could plausibly perform a write."""
    public_methods = [
        name
        for name, _ in inspect.getmembers(QuerySandboxService, predicate=inspect.isfunction)
        if not name.startswith("_")
    ]
    mutating_keywords = ("write", "insert", "update", "delete", "upsert", "create", "drop")
    offending = [
        m for m in public_methods if any(keyword in m.lower() for keyword in mutating_keywords)
    ]
    assert offending == []
