"""PII Egress Guard (C31) tests: SSN/EIN pattern detection, recursive
payload scanning, and that a plausible hashed field never false-positives.
See 02-design-document.md §3.21.
"""

from __future__ import annotations

import pytest

from fry14_engine.pii_egress.guard import PiiEgressBlockedError, PiiEgressGuard


@pytest.fixture
def guard() -> PiiEgressGuard:
    return PiiEgressGuard()


def test_clean_text_does_not_raise(guard: PiiEgressGuard):
    guard.scan_text("EAD rose 4.2% under the severely adverse scenario")


def test_ssn_shaped_text_is_blocked(guard: PiiEgressGuard):
    with pytest.raises(PiiEgressBlockedError) as exc_info:
        guard.scan_text("borrower SSN is 123-45-6789")
    assert exc_info.value.pattern_name == "SSN_FORMAT"


def test_ein_shaped_text_is_blocked(guard: PiiEgressGuard):
    with pytest.raises(PiiEgressBlockedError) as exc_info:
        guard.scan_text("EIN on file: 12-3456789")
    assert exc_info.value.pattern_name == "EIN_FORMAT"


def test_hashed_field_does_not_false_positive(guard: PiiEgressGuard):
    # A real HMAC-SHA256 hex digest — 64 hex chars, no dashes — must never
    # trip the SSN/EIN shape detectors.
    guard.scan_text("a" * 64)


def test_scan_payload_finds_pii_nested_in_dict(guard: PiiEgressGuard):
    payload = {"borrower": {"tax_id": "123-45-6789"}, "loan_id": "L-001"}
    with pytest.raises(PiiEgressBlockedError) as exc_info:
        guard.scan_payload(payload)
    assert exc_info.value.field_path == "$.borrower.tax_id"


def test_scan_payload_finds_pii_nested_in_list(guard: PiiEgressGuard):
    payload = {"notes": ["ok", "flag: 123-45-6789"]}
    with pytest.raises(PiiEgressBlockedError) as exc_info:
        guard.scan_payload(payload)
    assert exc_info.value.field_path == "$.notes[1]"


def test_scan_payload_ignores_non_string_leaves(guard: PiiEgressGuard):
    guard.scan_payload({"loan_count": 42, "dq_pass_rate": 0.98, "flagged": None, "active": True})


def test_scan_payload_clean_nested_structure_does_not_raise(guard: PiiEgressGuard):
    guard.scan_payload(
        {
            "scenario_run_id": "run-1",
            "comparisons": [
                {"quarter": 1, "delta_el": "1200.50"},
                {"quarter": 2, "delta_el": "900.00"},
            ],
        }
    )
