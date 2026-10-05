"""Data Product Catalog models (C12). See 02-design-document.md §2.8 and
schemas/008_catalog.sql.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from fry14_engine.common.enums import SlaStatus


class DataProductCatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    data_product_id: str
    health_score: Decimal
    dq_pass_percentage: Decimal
    sla_status: SlaStatus
    last_run_id: str | None
    owner: str | None


class SchemaVersionHistoryEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    data_product_id: str
    version: str
    effective_date: date
    changelog: str | None = None
