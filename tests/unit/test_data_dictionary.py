from __future__ import annotations

from pathlib import Path

from fry14_engine.contracts.data_dictionary import generate_data_dictionary
from fry14_engine.contracts.registry import ContractRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_commercial_loan_contract():
    registry = ContractRegistry(REPO_ROOT / "config" / "contracts")
    return registry.get_active("commercial_loan")


def test_generates_header_with_contract_id_and_version():
    contract = _load_commercial_loan_contract()
    doc = generate_data_dictionary(contract)
    assert f"# Data Dictionary: {contract.contract_id} v{contract.version}" in doc


def test_every_field_appears_as_a_table_row():
    contract = _load_commercial_loan_contract()
    doc = generate_data_dictionary(contract)
    for field in contract.fields:
        assert f"| {field.field_name} |" in doc


def test_non_nullable_fields_show_null_reason_code():
    contract = _load_commercial_loan_contract()
    doc = generate_data_dictionary(contract)
    assert "| credit_score | INT | False |  | - | MISSING_CREDIT_SCORE |" in doc


def test_nullable_pii_fields_show_no_spurious_null_reason_code():
    """A field that's nullable=True can never trigger its null_reason_code,
    so the dictionary must not list one for it."""
    contract = _load_commercial_loan_contract()
    doc = generate_data_dictionary(contract)
    assert "| borrower_tax_id | STRING | True | yes | - | - |" in doc


def test_range_constrained_field_shows_range_and_reason_code():
    contract = _load_commercial_loan_contract()
    doc = generate_data_dictionary(contract)
    assert "1-10" in doc
    assert "INVALID_CREDIT_GRADE" in doc


def test_enum_constrained_field_shows_allowed_values():
    contract = _load_commercial_loan_contract()
    doc = generate_data_dictionary(contract)
    assert "CRE, C&I" in doc


def test_business_rules_section_lists_each_rule():
    contract = _load_commercial_loan_contract()
    doc = generate_data_dictionary(contract)
    assert "## Business rules" in doc
    for rule in contract.business_rules:
        assert rule.rule_id in doc
