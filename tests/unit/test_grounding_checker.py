"""Numeric Grounding Checker (C29) tests: binding resolution, the
unbound-number scan, and the dates/quarter-labels/regulation-name
allowlist. See 02-design-document.md §3.19.
"""

from __future__ import annotations

from fry14_engine.grounding.checker import GroundingChecker
from fry14_engine.grounding.models import GroundingStatus


def _resolver(mapping: dict[str, str]):
    return lambda token: mapping.get(token)


def test_fully_bound_narrative_passes():
    checker = GroundingChecker()
    result = checker.check(
        "EL rose by {{run:abc.delta_el}} in Q3 2026.",
        _resolver({"run:abc.delta_el": "$1,200.50"}),
    )
    assert result.status == GroundingStatus.PASSED
    assert result.rendered_text == "EL rose by $1,200.50 in Q3 2026."
    assert result.unbound_numbers == []
    assert result.unresolved_tokens == []


def test_injected_free_number_is_blocked():
    checker = GroundingChecker()
    result = checker.check(
        "EL rose by $1,200.50 (12% increase) in Q3 2026.",
        _resolver({}),
    )
    assert result.status == GroundingStatus.FAILED
    assert result.unbound_numbers  # the raw $1,200.50 and 12% are both caught


def test_unresolvable_binding_is_blocked():
    checker = GroundingChecker()
    result = checker.check("EL rose by {{run:xyz.nope}}.", _resolver({}))
    assert result.status == GroundingStatus.FAILED
    assert result.unresolved_tokens == ["run:xyz.nope"]
    # The token is left in place, literally — still a {{...}} span, not a
    # bare number, so it isn't double-counted as an unbound number too.
    assert result.unbound_numbers == []


def test_quarter_labels_are_allowlisted():
    checker = GroundingChecker()
    result = checker.check("Compare Q1 to Q4 of the horizon.", _resolver({}))
    assert result.status == GroundingStatus.PASSED


def test_reporting_period_dates_are_allowlisted():
    checker = GroundingChecker()
    result = checker.check(
        "This covers the {{run:abc.period}} reporting period, filed 2026-06.",
        _resolver({"run:abc.period": "2026-06"}),
    )
    assert result.status == GroundingStatus.PASSED


def test_bare_year_is_allowlisted():
    checker = GroundingChecker()
    result = checker.check("The 2026 CCAR cycle.", _resolver({}))
    assert result.status == GroundingStatus.PASSED


def test_regulation_name_is_allowlisted():
    checker = GroundingChecker()
    result = checker.check("Filed under FR Y-14 and reviewed per CCAR.", _resolver({}))
    assert result.status == GroundingStatus.PASSED


def test_mix_of_bound_and_unbound_numbers_fails():
    checker = GroundingChecker()
    result = checker.check(
        "EL rose by {{run:abc.delta_el}}, roughly 15% more than planned.",
        _resolver({"run:abc.delta_el": "$1,200.50"}),
    )
    assert result.status == GroundingStatus.FAILED
    assert "15" in result.unbound_numbers


def test_no_bindings_and_no_numbers_passes():
    checker = GroundingChecker()
    result = checker.check("This is a purely qualitative statement.", _resolver({}))
    assert result.status == GroundingStatus.PASSED
    assert result.rendered_text == "This is a purely qualitative statement."
