from __future__ import annotations

from pathlib import Path

from fry14_engine.demo import format_report, run_demo


def test_run_demo_end_to_end(tmp_db_path: Path):
    result = run_demo(count=24, bad_record_rate=0.25, seed=11, db_path=tmp_db_path)
    report = result.report

    total_landed = sum(i.records_landed for i in report.ingestion_results)
    assert total_landed == 24
    assert report.validation.total_count == 24
    assert report.validation.quarantined_count > 0
    assert report.validation.governed_count + report.validation.quarantined_count == 24
    assert result.contract_id == "commercial_loan"
    assert (
        len(report.risk_calculation.metrics) + len(report.risk_calculation.exceptions)
        == report.validation.governed_count
    )
    assert report.aggregation.input_metric_count == len(report.risk_calculation.metrics)
    assert sum(row.loan_count for row in report.aggregation.aggregates) == len(
        report.risk_calculation.metrics
    )
    assert report.catalog.entry.data_product_id == "commercial_loan.schedule"
    assert report.catalog.entry.last_run_id == report.pipeline_run_id
    assert result.sandbox.allowed_row_count == len(report.aggregation.aggregates)
    assert result.sandbox.denied_as_expected is True

    # every stage traces back to the one pipeline_run_id
    assert result.audit_events  # the run left a reconstructable trail
    assert all(
        e.pipeline_run_id == report.pipeline_run_id
        for e in result.audit_events
        if e.pipeline_run_id is not None
    )
    event_types = {e.event_type for e in result.audit_events}
    assert {
        "INGESTION",
        "VALIDATION",
        "PII_HASH",
        "CALCULATION",
        "AGGREGATION",
        "CATALOG_UPDATE",
        "ORCHESTRATION",
    }.issubset(event_types)


def test_run_demo_is_reproducible_with_same_seed(tmp_db_path: Path, tmp_path: Path):
    first = run_demo(
        count=20, bad_record_rate=0.2, seed=99, db_path=tmp_db_path, reporting_period="2026-06"
    )
    second = run_demo(
        count=20,
        bad_record_rate=0.2,
        seed=99,
        db_path=tmp_path / "other.duckdb",
        reporting_period="2026-06",
    )

    assert first.report.validation.reason_code_counts == second.report.validation.reason_code_counts
    assert first.report.validation.quarantined_count == second.report.validation.quarantined_count
    first_totals = [(m.loan_id, m.ead, m.el, m.rwa) for m in first.report.risk_calculation.metrics]
    second_totals = [
        (m.loan_id, m.ead, m.el, m.rwa) for m in second.report.risk_calculation.metrics
    ]
    assert first_totals == second_totals


def test_format_report_is_plain_ascii(tmp_db_path: Path):
    result = run_demo(count=10, bad_record_rate=0.1, seed=3, db_path=tmp_db_path)
    report = format_report(result)
    report.encode("ascii")  # raises UnicodeEncodeError if any non-ASCII char slipped in
    assert "commercial_loan" in report
    assert "DQ pass rate" in report
    assert "Pipeline run id" in report
