from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from fry14_engine.contracts.models import (
    AllowedRange,
    BusinessRule,
    DataContract,
    FieldContract,
    FieldDataType,
)
from fry14_engine.contracts.validation_engine import ValidationEngine
from fry14_engine.ingestion.models import RawLoanRecord


@pytest.fixture
def contract() -> DataContract:
    return DataContract(
        contract_id="commercial_loan",
        version="1.0.0",
        effective_date=date(2026, 1, 1),
        fields=[
            FieldContract(field_name="loan_id", data_type=FieldDataType.STRING, nullable=False),
            FieldContract(
                field_name="internal_credit_risk_grade",
                data_type=FieldDataType.INT,
                nullable=False,
                allowed_range=AllowedRange(min=1, max=10),
                constraint_reason_code="INVALID_CREDIT_GRADE",
            ),
            FieldContract(
                field_name="credit_score",
                data_type=FieldDataType.INT,
                nullable=False,
                null_reason_code="MISSING_CREDIT_SCORE",
            ),
            FieldContract(
                field_name="outstanding_balance",
                data_type=FieldDataType.DECIMAL,
                nullable=False,
                allowed_range=AllowedRange(min=Decimal(0)),
                constraint_reason_code="NEGATIVE_BALANCE",
            ),
            FieldContract(
                field_name="asset_class",
                data_type=FieldDataType.STRING,
                nullable=False,
                allowed_values=["CRE", "C&I"],
                constraint_reason_code="UNKNOWN_ASSET_CLASS",
            ),
        ],
        business_rules=[
            BusinessRule(
                rule_id="MATURITY_BEFORE_ORIGINATION",
                description="maturity after origination",
                expression="maturity_date >= origination_date",
            )
        ],
    )


def _good_record(**overrides) -> RawLoanRecord:
    base = {
        "loan_id": "LN-1",
        "internal_credit_risk_grade": 5,
        "credit_score": 700,
        "outstanding_balance": Decimal("1000.00"),
        "asset_class": "CRE",
        "origination_date": date(2026, 1, 1),
        "maturity_date": date(2027, 1, 1),
    }
    base.update(overrides)
    return RawLoanRecord.model_validate(base)


def test_fully_valid_record_has_no_reason_codes(contract):
    engine = ValidationEngine(contract)
    outcome = engine.validate(_good_record())
    assert outcome.is_valid
    assert outcome.reason_codes == ()


def test_null_mandatory_field_without_override_uses_generic_code(contract):
    engine = ValidationEngine(contract)
    outcome = engine.validate(_good_record(asset_class=None))
    assert not outcome.is_valid
    assert "NULL_MANDATORY_FIELD" in outcome.reason_codes


def test_missing_credit_score_uses_specific_code(contract):
    engine = ValidationEngine(contract)
    outcome = engine.validate(_good_record(credit_score=None))
    assert "MISSING_CREDIT_SCORE" in outcome.reason_codes
    assert "NULL_MANDATORY_FIELD" not in outcome.reason_codes


@pytest.mark.parametrize("grade", [0, 11, 99])
def test_out_of_range_grade(contract, grade):
    engine = ValidationEngine(contract)
    outcome = engine.validate(_good_record(internal_credit_risk_grade=grade))
    assert "INVALID_CREDIT_GRADE" in outcome.reason_codes


def test_negative_balance(contract):
    engine = ValidationEngine(contract)
    outcome = engine.validate(_good_record(outstanding_balance=Decimal("-500.00")))
    assert "NEGATIVE_BALANCE" in outcome.reason_codes


def test_unknown_asset_class(contract):
    engine = ValidationEngine(contract)
    outcome = engine.validate(_good_record(asset_class="RESIDENTIAL"))
    assert "UNKNOWN_ASSET_CLASS" in outcome.reason_codes


def test_business_rule_violation(contract):
    engine = ValidationEngine(contract)
    outcome = engine.validate(
        _good_record(origination_date=date(2027, 1, 1), maturity_date=date(2026, 1, 1))
    )
    assert "MATURITY_BEFORE_ORIGINATION" in outcome.reason_codes


def test_type_mismatch_detected_at_field_check_level():
    """RawLoanRecord already coerces types at ingestion, so this path is
    defense-in-depth for records validated outside that flow — exercised
    directly against the field-check helper."""
    field = FieldContract(
        field_name="internal_credit_risk_grade",
        data_type=FieldDataType.INT,
        nullable=False,
    )
    codes = ValidationEngine._check_field(field, {"internal_credit_risk_grade": "not-a-number"})
    assert codes == ["TYPE_MISMATCH"]


def test_multiple_simultaneous_violations_all_captured(contract):
    engine = ValidationEngine(contract)
    outcome = engine.validate(
        _good_record(
            credit_score=None,
            internal_credit_risk_grade=0,
            outstanding_balance=Decimal("-1.00"),
        )
    )
    assert set(outcome.reason_codes) == {
        "MISSING_CREDIT_SCORE",
        "INVALID_CREDIT_GRADE",
        "NEGATIVE_BALANCE",
    }
