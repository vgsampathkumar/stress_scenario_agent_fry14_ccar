from __future__ import annotations

from datetime import date
from decimal import Decimal

from fry14_engine.contracts.models import (
    AllowedRange,
    BusinessRule,
    DataContract,
    FieldContract,
    FieldDataType,
)


def test_field_contract_defaults():
    field = FieldContract(field_name="asset_class", data_type=FieldDataType.STRING)
    assert field.nullable is True
    assert field.pii is False
    assert field.null_reason_code == "NULL_MANDATORY_FIELD"
    assert field.constraint_reason_code == "TYPE_MISMATCH"


def test_allowed_range_accepts_partial_bounds():
    range_ = AllowedRange(min=0)
    assert range_.min == Decimal(0)
    assert range_.max is None


def test_data_contract_parses_full_document():
    contract = DataContract(
        contract_id="commercial_loan",
        version="1.0.0",
        effective_date=date(2026, 1, 1),
        fields=[
            FieldContract(
                field_name="internal_credit_risk_grade",
                data_type=FieldDataType.INT,
                nullable=False,
                allowed_range=AllowedRange(min=1, max=10),
                constraint_reason_code="INVALID_CREDIT_GRADE",
            )
        ],
        business_rules=[
            BusinessRule(
                rule_id="MATURITY_BEFORE_ORIGINATION",
                description="maturity after origination",
                expression="maturity_date >= origination_date",
            )
        ],
    )
    assert contract.contract_id == "commercial_loan"
    assert len(contract.fields) == 1
    assert contract.business_rules[0].rule_id == "MATURITY_BEFORE_ORIGINATION"


def test_real_contract_yaml_loads_via_registry():
    from pathlib import Path

    from fry14_engine.contracts.registry import ContractRegistry

    repo_root = Path(__file__).resolve().parents[2]
    registry = ContractRegistry(repo_root / "config" / "contracts")
    contract = registry.get_active("commercial_loan")

    assert contract.version == "1.0.0"
    field_names = {f.field_name for f in contract.fields}
    assert {
        "loan_id",
        "internal_credit_risk_grade",
        "credit_score",
        "outstanding_balance",
        "asset_class",
    }.issubset(field_names)
    pii_fields = {f.field_name for f in contract.fields if f.pii}
    assert pii_fields == {"borrower_tax_id", "borrower_legal_name", "borrower_address"}
