-- Computed per-loan risk metrics (EAD / EL / RWA), versioned for reproducibility.
-- See 02-design-document.md §2.6, §3.5.

CREATE TABLE IF NOT EXISTS metrics.loan_risk_metrics (
    loan_id                        VARCHAR NOT NULL,
    reporting_period                VARCHAR NOT NULL,   -- 'YYYY-MM'
    ead                              DECIMAL(18, 2) NOT NULL,
    el                                DECIMAL(18, 2) NOT NULL,
    rwa                               DECIMAL(18, 2) NOT NULL,
    asset_class                      VARCHAR NOT NULL,
    portfolio_segment                VARCHAR NOT NULL,
    credit_rating_grade              INTEGER NOT NULL,
    remaining_maturity_bucket         VARCHAR NOT NULL
        CHECK (remaining_maturity_bucket IN ('0-12M', '13-36M', '37-60M', '60M+')),
    calc_engine_version               VARCHAR NOT NULL,
    regulatory_parameter_version       VARCHAR NOT NULL,
    pipeline_run_id                    VARCHAR NOT NULL,
    computed_at                         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (loan_id, reporting_period, pipeline_run_id)
);

CREATE INDEX IF NOT EXISTS idx_metrics_period ON metrics.loan_risk_metrics (reporting_period);

-- Calculation exceptions (e.g. missing PD/LGD): parallel "fail-forward" path
-- so a single loan's calc failure never blocks the rest of the run.
CREATE TABLE IF NOT EXISTS metrics.calculation_exception (
    exception_id        UUID PRIMARY KEY,
    loan_id               VARCHAR NOT NULL,
    pipeline_run_id        VARCHAR NOT NULL,
    reason_code             VARCHAR NOT NULL,
    detail                    VARCHAR,
    raised_at                 TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
