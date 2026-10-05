"""RBAC / IAM Module (C14): role-permission enforcement. See
02-design-document.md §2.9, §3.9.

This is the human/service-principal RBAC layer. It has no notion of
"agent" — agent autonomy limits are a separate, later concern owned by the
Policy Enforcement Point (C24, Phase 9), which additionally intersects a
user's RBAC permissions with the calling agent's tool allowlist.
"""

from __future__ import annotations

from fry14_engine.common.enums import Permission, RoleName
from fry14_engine.rbac.matrix import ROLE_PERMISSION_MATRIX


class PermissionDeniedError(Exception):
    def __init__(self, role: RoleName, permission: Permission) -> None:
        super().__init__(f"Role {role} does not have permission {permission}")
        self.role = role
        self.permission = permission


class RbacService:
    def has_permission(self, role: RoleName, permission: Permission) -> bool:
        return permission in ROLE_PERMISSION_MATRIX.get(role, frozenset())

    def require_permission(self, role: RoleName, permission: Permission) -> None:
        """Raise `PermissionDeniedError` if `role` lacks `permission`.
        Every permission check — allow or deny — is meant to be logged to
        the audit trail (C15, Phase 7); that wiring isn't built yet, so
        callers in this phase only get the raise/no-raise behavior."""
        if not self.has_permission(role, permission):
            raise PermissionDeniedError(role, permission)
