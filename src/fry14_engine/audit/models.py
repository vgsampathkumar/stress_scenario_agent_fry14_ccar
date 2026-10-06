"""Audit event model. See 02-design-document.md §3.10 and
schemas/010_audit.sql.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    pipeline_run_id: str | None
    event_type: str
    actor: str | None = None
    detail: dict[str, Any] | None = None
