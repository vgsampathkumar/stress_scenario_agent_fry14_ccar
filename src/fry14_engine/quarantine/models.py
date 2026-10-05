"""Quarantine record model. See 02-design-document.md §2.3 and
schemas/003_quarantine.sql.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from fry14_engine.common.enums import RemediationStatus


class QuarantineRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    quarantine_id: str
    loan_id: str
    pipeline_run_id: str
    contract_id: str
    contract_version: str
    original_record: dict[str, Any]
    exception_reason_codes: tuple[str, ...] = Field(min_length=1)
    rejected_at: datetime
    remediation_status: RemediationStatus = RemediationStatus.OPEN
