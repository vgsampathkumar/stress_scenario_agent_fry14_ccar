from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from fry14_engine.ingestion.models import RawLoanRecord


def test_coerces_csv_style_string_fields():
    record = RawLoanRecord.model_validate(
        {
            "loan_id": "LN-1",
            "internal_credit_risk_grade": "5",
            "outstanding_balance": "1000.50",
            "maturity_date": "2030-01-01",
            "asset_class": "C&I",
        }
    )
    assert record.internal_credit_risk_grade == 5
    assert record.outstanding_balance == Decimal("1000.50")
    assert record.maturity_date.isoformat() == "2030-01-01"


def test_missing_optional_fields_become_none():
    record = RawLoanRecord.model_validate({"loan_id": "LN-1"})
    assert record.credit_score is None
    assert record.outstanding_balance is None


def test_out_of_range_business_values_still_parse():
    """Ingestion only coerces types; range/business-rule checks are Phase 2's job."""
    record = RawLoanRecord.model_validate(
        {
            "loan_id": "LN-1",
            "internal_credit_risk_grade": 99,
            "outstanding_balance": "-500.00",
        }
    )
    assert record.internal_credit_risk_grade == 99
    assert record.outstanding_balance == Decimal("-500.00")


def test_missing_loan_id_fails_validation():
    with pytest.raises(ValidationError):
        RawLoanRecord.model_validate({"asset_class": "CRE"})


def test_unrecognized_fields_are_ignored():
    record = RawLoanRecord.model_validate({"loan_id": "LN-1", "some_unmapped_field": "x"})
    assert record.loan_id == "LN-1"
