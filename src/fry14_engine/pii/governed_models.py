"""Governed (post-contract-validation, post-PII-hash, pre-risk-calc) loan
record model. See 02-design-document.md §2.4 and schemas/004_governed.sql —
nullability here intentionally mirrors that DDL exactly.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class GovernedLoanRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    governed_id: str
    loan_id: str
    borrower_key_hash: str | None
    borrower_name_hash: str | None
    borrower_address_hash: str | None
    counterparty_id: str | None
    asset_class: str
    internal_credit_risk_grade: int
    credit_score: int
    outstanding_balance: Decimal
    unadvanced_commitment: Decimal | None
    maturity_date: date | None
    probability_of_default: Decimal | None
    loss_given_default: Decimal | None
    portfolio_segment: str | None
    pipeline_run_id: str
    contract_version: str
    ingestion_timestamp: datetime
