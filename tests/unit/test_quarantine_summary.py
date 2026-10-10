"""`get_quarantine_summary` clustering tests (Phase 10, C19's deterministic
data tool). See 02-design-document.md §3.17.
"""

from __future__ import annotations

from datetime import datetime

from fry14_engine.quarantine.models import QuarantineRecord
from fry14_engine.quarantine.summary import MAX_SAMPLES_PER_CLUSTER, build_quarantine_summary


def _record(
    quarantine_id: str,
    reason_codes: tuple[str, ...],
    source_system: str | None,
    rejected_at: datetime,
    **field_overrides,
) -> QuarantineRecord:
    original_record = {
        "loan_id": f"LN-{quarantine_id}",
        "credit_score": 700,
        "outstanding_balance": 100.0,
        "source_system_of_record": source_system,
        **field_overrides,
    }
    return QuarantineRecord(
        quarantine_id=quarantine_id,
        loan_id=f"LN-{quarantine_id}",
        pipeline_run_id="run-1",
        contract_id="commercial_loan",
        contract_version="1.0.0",
        original_record=original_record,
        exception_reason_codes=reason_codes,
        rejected_at=rejected_at,
    )


def test_empty_input_produces_empty_summary():
    summary = build_quarantine_summary([])
    assert summary.total_open_records == 0
    assert summary.clusters == []


def test_clusters_by_reason_code_and_source_system():
    day = datetime(2026, 6, 1, 12, 0, 0)
    records = [
        _record("q1", ("MISSING_CREDIT_SCORE",), "LEGACY_CORE", day, credit_score=None),
        _record("q2", ("MISSING_CREDIT_SCORE",), "LEGACY_CORE", day, credit_score=None),
        _record("q3", ("NEGATIVE_BALANCE",), "MODERN_CORE", day, outstanding_balance=-50.0),
    ]
    summary = build_quarantine_summary(records)

    assert summary.total_open_records == 3
    assert len(summary.clusters) == 2
    missing_credit_cluster = next(
        c for c in summary.clusters if c.reason_code == "MISSING_CREDIT_SCORE"
    )
    assert missing_credit_cluster.source_system_of_record == "LEGACY_CORE"
    assert missing_credit_cluster.record_count == 2
    assert missing_credit_cluster.null_field_rates["credit_score"] == 1.0


def test_record_with_multiple_reason_codes_contributes_to_each_cluster():
    day = datetime(2026, 6, 1)
    records = [_record("q1", ("NEGATIVE_BALANCE", "MISSING_CREDIT_SCORE"), "CORE", day)]
    summary = build_quarantine_summary(records)
    assert {c.reason_code for c in summary.clusters} == {"NEGATIVE_BALANCE", "MISSING_CREDIT_SCORE"}
    assert all(c.record_count == 1 for c in summary.clusters)


def test_different_rejection_days_form_separate_clusters():
    records = [
        _record("q1", ("MISSING_CREDIT_SCORE",), "CORE", datetime(2026, 6, 1)),
        _record("q2", ("MISSING_CREDIT_SCORE",), "CORE", datetime(2026, 6, 2)),
    ]
    summary = build_quarantine_summary(records)
    assert len(summary.clusters) == 2
    assert all(c.record_count == 1 for c in summary.clusters)


def test_samples_are_capped_at_max_per_cluster():
    day = datetime(2026, 6, 1)
    records = [
        _record(f"q{i}", ("MISSING_CREDIT_SCORE",), "CORE", day)
        for i in range(MAX_SAMPLES_PER_CLUSTER + 5)
    ]
    summary = build_quarantine_summary(records)
    cluster = summary.clusters[0]
    assert cluster.record_count == MAX_SAMPLES_PER_CLUSTER + 5
    assert len(cluster.sample_quarantine_ids) == MAX_SAMPLES_PER_CLUSTER


def test_null_field_rates_cover_every_field_seen_in_cluster():
    day = datetime(2026, 6, 1)
    records = [
        _record("q1", ("MISSING_CREDIT_SCORE",), "CORE", day, credit_score=None, extra_field="x"),
        _record("q2", ("MISSING_CREDIT_SCORE",), "CORE", day, credit_score=None, extra_field=None),
    ]
    summary = build_quarantine_summary(records)
    rates = summary.clusters[0].null_field_rates
    assert rates["credit_score"] == 1.0
    assert rates["extra_field"] == 0.5
