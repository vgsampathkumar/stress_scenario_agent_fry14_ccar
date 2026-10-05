from __future__ import annotations

from pathlib import Path

from fry14_engine.demo import format_report, run_demo


def test_run_demo_end_to_end(tmp_db_path: Path):
    result = run_demo(count=24, bad_record_rate=0.25, seed=11, db_path=tmp_db_path)

    assert result.batch_ingest.records_landed + result.event_ingest.records_landed == 24
    assert result.validation.total_count == 24
    assert result.validation.quarantined_count > 0
    assert result.validation.governed_count + result.validation.quarantined_count == 24
    assert result.contract_id == "commercial_loan"
    assert (
        len(result.risk_calculation.metrics) + len(result.risk_calculation.exceptions)
        == result.validation.governed_count
    )
    assert result.aggregation.input_metric_count == len(result.risk_calculation.metrics)
    assert sum(row.loan_count for row in result.aggregation.aggregates) == len(
        result.risk_calculation.metrics
    )
    assert result.catalog.entry.data_product_id == "commercial_loan.schedule"
    assert result.catalog.entry.last_run_id is not None
    assert result.sandbox.allowed_row_count == len(result.aggregation.aggregates)
    assert result.sandbox.denied_as_expected is True


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

    assert first.validation.reason_code_counts == second.validation.reason_code_counts
    assert first.validation.quarantined_count == second.validation.quarantined_count
    first_totals = [(m.loan_id, m.ead, m.el, m.rwa) for m in first.risk_calculation.metrics]
    second_totals = [(m.loan_id, m.ead, m.el, m.rwa) for m in second.risk_calculation.metrics]
    assert first_totals == second_totals


def test_format_report_is_plain_ascii(tmp_db_path: Path):
    result = run_demo(count=10, bad_record_rate=0.1, seed=3, db_path=tmp_db_path)
    report = format_report(result)
    report.encode("ascii")  # raises UnicodeEncodeError if any non-ASCII char slipped in
    assert "commercial_loan" in report
    assert "DQ pass rate" in report
