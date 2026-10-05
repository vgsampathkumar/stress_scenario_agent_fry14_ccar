from __future__ import annotations

from decimal import Decimal

import pytest

from fry14_engine.aggregation.engine import AGGREGATE_SCHEMA_VERSION, AggregationEngine
from fry14_engine.common.enums import MaturityBucket
from fry14_engine.risk_engine.models import LoanRiskMetrics


def _metric(**overrides) -> LoanRiskMetrics:
    base = dict(
        loan_id="LN-1",
        reporting_period="2026-06",
        ead=Decimal("1000000.00"),
        el=Decimal("9000.00"),
        rwa=Decimal("1000000.00"),
        asset_class="CRE",
        portfolio_segment="MIDDLE_MARKET",
        credit_rating_grade=5,
        remaining_maturity_bucket=MaturityBucket.M_13_36,
        calc_engine_version="1.0.0",
        regulatory_parameter_version="1.0.0",
        pipeline_run_id="run-1",
    )
    base.update(overrides)
    return LoanRiskMetrics(**base)


def test_single_group_sums_and_counts_correctly():
    engine = AggregationEngine()
    metrics = [
        _metric(
            loan_id="LN-1",
            ead=Decimal("1000000.00"),
            el=Decimal("9000.00"),
            rwa=Decimal("1000000.00"),
        ),
        _metric(
            loan_id="LN-2",
            ead=Decimal("500000.00"),
            el=Decimal("4500.00"),
            rwa=Decimal("500000.00"),
        ),
    ]

    aggregates = engine.run(metrics, pipeline_run_id="run-1")

    assert len(aggregates) == 1
    row = aggregates[0]
    assert row.total_ead == Decimal("1500000.00")
    assert row.total_el == Decimal("13500.00")
    assert row.total_rwa == Decimal("1500000.00")
    assert row.loan_count == 2
    assert row.schema_version == AGGREGATE_SCHEMA_VERSION


def test_different_segments_produce_separate_rows():
    engine = AggregationEngine()
    metrics = [
        _metric(loan_id="LN-1", portfolio_segment="MIDDLE_MARKET"),
        _metric(loan_id="LN-2", portfolio_segment="LARGE_CORPORATE"),
    ]

    aggregates = engine.run(metrics, pipeline_run_id="run-1")

    assert len(aggregates) == 2
    segments = {row.portfolio_segment for row in aggregates}
    assert segments == {"MIDDLE_MARKET", "LARGE_CORPORATE"}
    assert all(row.loan_count == 1 for row in aggregates)


def test_different_grades_produce_separate_rows():
    engine = AggregationEngine()
    metrics = [
        _metric(loan_id="LN-1", credit_rating_grade=1),
        _metric(loan_id="LN-2", credit_rating_grade=10),
    ]

    aggregates = engine.run(metrics, pipeline_run_id="run-1")
    assert len(aggregates) == 2


def test_different_maturity_buckets_produce_separate_rows():
    engine = AggregationEngine()
    metrics = [
        _metric(loan_id="LN-1", remaining_maturity_bucket=MaturityBucket.M_0_12),
        _metric(loan_id="LN-2", remaining_maturity_bucket=MaturityBucket.M_60_PLUS),
    ]

    aggregates = engine.run(metrics, pipeline_run_id="run-1")
    assert len(aggregates) == 2


def test_different_reporting_periods_produce_separate_rows():
    engine = AggregationEngine()
    metrics = [
        _metric(loan_id="LN-1", reporting_period="2026-06"),
        _metric(loan_id="LN-2", reporting_period="2026-07"),
    ]

    aggregates = engine.run(metrics, pipeline_run_id="run-1")
    assert len(aggregates) == 2


def test_empty_input_produces_no_aggregates():
    engine = AggregationEngine()
    assert engine.run([], pipeline_run_id="run-1") == []


def test_aggregate_totals_reconcile_exactly_with_sum_of_inputs():
    engine = AggregationEngine()
    metrics = [_metric(loan_id=f"LN-{i}", ead=Decimal(f"{i}00.00")) for i in range(1, 11)]

    aggregates = engine.run(metrics, pipeline_run_id="run-1")

    expected_total_ead = sum((m.ead for m in metrics), start=Decimal("0"))
    assert len(aggregates) == 1
    assert aggregates[0].total_ead == expected_total_ead
    assert aggregates[0].loan_count == 10


def test_custom_schema_version_is_stamped():
    engine = AggregationEngine(schema_version="2.0.0")
    aggregates = engine.run([_metric()], pipeline_run_id="run-1")
    assert aggregates[0].schema_version == "2.0.0"


@pytest.mark.parametrize("bucket", list(MaturityBucket))
def test_all_maturity_buckets_are_valid_group_keys(bucket):
    engine = AggregationEngine()
    aggregates = engine.run([_metric(remaining_maturity_bucket=bucket)], pipeline_run_id="run-1")
    assert aggregates[0].remaining_maturity_bucket == bucket
