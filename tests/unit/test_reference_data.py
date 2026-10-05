from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from fry14_engine.reference_data.models import ReferenceDataNotFoundError, RegulatoryParameterSet


@pytest.fixture
def parameter_set() -> RegulatoryParameterSet:
    return RegulatoryParameterSet(
        version="1.0.0",
        effective_date=date(2026, 1, 1),
        ccf_by_key={("CRE", "STANDARD"): Decimal("0.5"), ("C&I", "STANDARD"): Decimal("0.2")},
        risk_weight_by_asset_class={"CRE": Decimal("1.00"), "C&I": Decimal("1.00")},
    )


def test_get_ccf_known_key(parameter_set):
    assert parameter_set.get_ccf("CRE", "STANDARD") == Decimal("0.5")


def test_get_ccf_unknown_key_raises(parameter_set):
    with pytest.raises(ReferenceDataNotFoundError):
        parameter_set.get_ccf("RESIDENTIAL", "STANDARD")


def test_get_risk_weight_known_asset_class(parameter_set):
    assert parameter_set.get_risk_weight("C&I") == Decimal("1.00")


def test_get_risk_weight_unknown_asset_class_raises(parameter_set):
    with pytest.raises(ReferenceDataNotFoundError):
        parameter_set.get_risk_weight("RESIDENTIAL")
