-- Schedule Aggregate: the published, schema-versioned data product consumed
-- by the catalog and query sandbox. See 02-design-document.md §2.7, §3.6.

CREATE TABLE IF NOT EXISTS aggregates.schedule_aggregate (
    reporting_period             VARCHAR NOT NULL,   -- 'YYYY-MM'
    portfolio_segment             VARCHAR NOT NULL,
    credit_rating_grade            INTEGER NOT NULL,
    remaining_maturity_bucket       VARCHAR NOT NULL,
    total_ead                        DECIMAL(22, 2) NOT NULL,
    total_el                          DECIMAL(22, 2) NOT NULL,
    total_rwa                         DECIMAL(22, 2) NOT NULL,
    loan_count                         INTEGER NOT NULL,
    schema_version                     VARCHAR NOT NULL,
    pipeline_run_id                     VARCHAR NOT NULL,
    generated_at                         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (reporting_period, portfolio_segment, credit_rating_grade,
                 remaining_maturity_bucket, schema_version)
);
