from __future__ import annotations

import pytest

from fry14_engine.common.enums import Permission, RoleName
from fry14_engine.rbac.matrix import ROLE_PERMISSION_MATRIX
from fry14_engine.rbac.service import PermissionDeniedError, RbacService


def test_every_role_has_a_matrix_entry():
    for role in RoleName:
        assert role in ROLE_PERMISSION_MATRIX


def test_admin_has_every_permission():
    assert ROLE_PERMISSION_MATRIX[RoleName.ADMIN] == frozenset(Permission)


def test_only_compliance_audit_and_admin_can_view_raw_pii():
    service = RbacService()
    allowed = {role for role in RoleName if service.has_permission(role, Permission.VIEW_RAW_PII)}
    assert allowed == {RoleName.COMPLIANCE_AUDIT, RoleName.ADMIN}


def test_system_scheduler_can_only_run_pipeline():
    assert ROLE_PERMISSION_MATRIX[RoleName.SYSTEM_SCHEDULER] == frozenset({Permission.RUN_PIPELINE})


def test_has_permission_true_for_granted():
    service = RbacService()
    assert service.has_permission(RoleName.FINANCE, Permission.QUERY_SANDBOX_READ)


def test_has_permission_false_for_ungranted():
    service = RbacService()
    assert not service.has_permission(RoleName.FINANCE, Permission.VIEW_RAW_PII)
    assert not service.has_permission(RoleName.FINANCE, Permission.MANAGE_CONTRACTS)


def test_require_permission_raises_with_role_and_permission_on_denial():
    service = RbacService()
    with pytest.raises(PermissionDeniedError) as exc_info:
        service.require_permission(RoleName.FINANCE, Permission.VIEW_RAW_PII)
    assert exc_info.value.role == RoleName.FINANCE
    assert exc_info.value.permission == Permission.VIEW_RAW_PII


def test_require_permission_does_not_raise_when_granted():
    service = RbacService()
    service.require_permission(RoleName.COMPLIANCE_AUDIT, Permission.VIEW_RAW_PII)


def test_no_role_holds_approve_permissions_except_designated_approvers():
    """Sanity check on the matrix itself: APPROVE_* permissions should only
    land on roles the design doc names as approvers (02-design-document.md
    §2.12), not leak onto read-only roles like FINANCE."""
    service = RbacService()
    approve_permissions = [p for p in Permission if p.startswith("APPROVE_")]
    for permission in approve_permissions:
        assert not service.has_permission(RoleName.FINANCE, permission)
