from __future__ import annotations

import pytest

from fry14_engine.synthetic.generator import generate_loan_records


def test_generates_requested_count():
    records = generate_loan_records(count=50, seed=1)
    assert len(records) == 50
    assert len({r["loan_id"] for r in records}) == 50  # unique loan_ids


def test_zero_bad_rate_produces_business_valid_records():
    records = generate_loan_records(count=30, bad_record_rate=0.0, seed=2)
    for r in records:
        assert r["outstanding_balance"] >= 0
        assert r["credit_score"] is not None
        assert 1 <= r["internal_credit_risk_grade"] <= 10
        assert r["asset_class"] is not None


def test_bad_record_rate_injects_known_exception_patterns():
    records = generate_loan_records(count=40, bad_record_rate=0.25, seed=3)

    has_negative_balance = any(r["outstanding_balance"] < 0 for r in records)
    has_missing_credit_score = any(r["credit_score"] is None for r in records)
    has_invalid_grade = any(
        r["internal_credit_risk_grade"] is not None
        and not (1 <= r["internal_credit_risk_grade"] <= 10)
        for r in records
    )
    has_null_asset_class = any(r["asset_class"] is None for r in records)

    assert has_negative_balance
    assert has_missing_credit_score
    assert has_invalid_grade
    assert has_null_asset_class


def test_same_seed_is_reproducible():
    first = generate_loan_records(count=25, bad_record_rate=0.2, seed=99)
    second = generate_loan_records(count=25, bad_record_rate=0.2, seed=99)
    assert first == second


def test_rejects_out_of_range_bad_record_rate():
    with pytest.raises(ValueError):
        generate_loan_records(count=5, bad_record_rate=1.5)
