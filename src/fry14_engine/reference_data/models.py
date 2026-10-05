"""Reference Data Store (C9) models: an in-memory, versioned regulatory
parameter set (CCF table, risk-weight table), loaded once from the DB and
handed to the (pure) Risk Metric Engine rather than queried per loan. See
02-design-document.md §2.5, §3.4.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


class ReferenceDataNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class RegulatoryParameterSet:
    version: str
    effective_date: date
    ccf_by_key: dict[tuple[str, str], Decimal]
    risk_weight_by_asset_class: dict[str, Decimal]

    def get_ccf(self, asset_class: str, commitment_type: str) -> Decimal:
        try:
            return self.ccf_by_key[(asset_class, commitment_type)]
        except KeyError:
            raise ReferenceDataNotFoundError(
                f"No CCF for asset_class={asset_class!r}, commitment_type={commitment_type!r} "
                f"under parameter version {self.version!r}"
            ) from None

    def get_risk_weight(self, asset_class: str) -> Decimal:
        try:
            return self.risk_weight_by_asset_class[asset_class]
        except KeyError:
            raise ReferenceDataNotFoundError(
                f"No risk weight for asset_class={asset_class!r} under parameter version "
                f"{self.version!r}"
            ) from None
