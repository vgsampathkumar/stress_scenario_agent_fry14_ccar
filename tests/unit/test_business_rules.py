from __future__ import annotations

from datetime import date

from fry14_engine.contracts.business_rules import maturity_after_origination


def test_passes_when_maturity_after_origination():
    record = {"origination_date": date(2026, 1, 1), "maturity_date": date(2027, 1, 1)}
    assert maturity_after_origination(record) is True


def test_fails_when_maturity_before_origination():
    record = {"origination_date": date(2026, 1, 1), "maturity_date": date(2025, 1, 1)}
    assert maturity_after_origination(record) is False


def test_passes_when_equal_dates():
    record = {"origination_date": date(2026, 1, 1), "maturity_date": date(2026, 1, 1)}
    assert maturity_after_origination(record) is True


def test_passes_when_either_field_missing():
    assert maturity_after_origination({"origination_date": None, "maturity_date": date(2026, 1, 1)})
    assert maturity_after_origination({"origination_date": date(2026, 1, 1), "maturity_date": None})
    assert maturity_after_origination({})
