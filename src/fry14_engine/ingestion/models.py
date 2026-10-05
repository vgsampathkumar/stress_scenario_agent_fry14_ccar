"""Canonical in-flight record shape used by all ingestion adapters.

Both the batch file adapter and the event stream adapter normalize their
source-specific payloads into this shape before metadata stamping and
landing-zone persistence. See 02-design-document.md §2.1, §3.1.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class RawLoanRecord(BaseModel):
    """Pre-contract-validation loan record.

    Deliberately permissive: type *coercion* happens here (e.g. a numeric
    string from a CSV row becomes an `int`/`Decimal`/`date`), but range,
    non-null, and other business-rule validation is Phase 2's job (the
    Contract Engine), not ingestion's. A record that coerces cleanly lands
    even if, say, its balance is negative or its grade is out of range —
    those are quarantined downstream, not rejected at the door (requirement
    2.2: "Pipeline processing must continue uninterrupted for valid
    records" — ingestion must not pre-empt that by being falsely strict).
    """

    model_config = ConfigDict(extra="ignore")

    loan_id: str
    borrower_tax_id: str | None = None
    borrower_legal_name: str | None = None
    borrower_address: str | None = None
    counterparty_id: str | None = None
    asset_class: str | None = None
    internal_credit_risk_grade: int | None = None
    credit_score: int | None = None
    outstanding_balance: Decimal | None = None
    unadvanced_commitment: Decimal | None = None
    origination_date: date | None = None
    maturity_date: date | None = None
    probability_of_default: Decimal | None = None
    loss_given_default: Decimal | None = None
    portfolio_segment: str | None = None
    source_system_of_record: str | None = None
