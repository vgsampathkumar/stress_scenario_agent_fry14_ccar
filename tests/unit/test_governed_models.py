from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fry14_engine.pii.governed_models import GovernedLoanRecord


def _record(**overrides) -> GovernedLoanRecord:
    base = dict(
        governed_id="g-1",
        loan_id="LN-1",
        borrower_key_hash="hash-tax-id",
        borrower_name_hash="hash-name",
        borrower_address_hash="hash-address",
        counterparty_id="CP-1",
        asset_class="CRE",
        internal_credit_risk_grade=5,
        credit_score=700,
        outstanding_balance=Decimal("1000.00"),
        unadvanced_commitment=Decimal("500.00"),
        maturity_date=None,
        probability_of_default=Decimal("0.02"),
        loss_given_default=Decimal("0.4"),
        portfolio_segment="MIDDLE_MARKET",
        pipeline_run_id="run-1",
        contract_version="1.0.0",
        ingestion_timestamp=datetime(2026, 1, 1),
    )
    base.update(overrides)
    return GovernedLoanRecord(**base)


def test_governed_record_allows_null_pii_hashes_and_deferred_fields():
    record = _record(
        borrower_key_hash=None,
        borrower_name_hash=None,
        borrower_address_hash=None,
        unadvanced_commitment=None,
        maturity_date=None,
        probability_of_default=None,
        loss_given_default=None,
        portfolio_segment=None,
    )
    assert record.borrower_key_hash is None
    assert record.probability_of_default is None


def test_governed_record_requires_core_contract_guaranteed_fields():
    record = _record()
    assert record.loan_id == "LN-1"
    assert record.asset_class == "CRE"
    assert record.internal_credit_risk_grade == 5
