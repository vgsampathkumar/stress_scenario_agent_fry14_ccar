-- Scenario specs and stress run results. See 02-design-document.md §2.10
-- (ScenarioSpec, StressedLoanMetrics, ScenarioRunResult) and §3.18 (Stress
-- Engine, C28). loan_id is a plain VARCHAR, not FK'd, mirroring
-- metrics.loan_risk_metrics.

-- Nested structures (portfolio_scope, adhoc_shocks, grade_migration) are
-- stored as JSON rather than normalized tables — they're read/written
-- whole (never queried by sub-field from SQL), same rationale as
-- quarantine.quarantine_record.original_record.
CREATE TABLE IF NOT EXISTS scenario.scenario_spec (
    scenario_spec_id        VARCHAR PRIMARY KEY,   -- uuid
    source_request_text       VARCHAR,
    base_scenario               VARCHAR NOT NULL
        CHECK (base_scenario IN ('BASELINE', 'SEVERELY_ADVERSE', 'NONE')),
    supervisory_scenario_version VARCHAR,
    reporting_period              VARCHAR NOT NULL,   -- 'YYYY-MM' of the governed base data
    portfolio_scope                JSON,                -- {portfolio_segments, asset_classes, credit_grades}
    adhoc_shocks                     JSON,                -- [{variable, shock_type, magnitude, quarters}]
    grade_migration                    JSON,               -- {notches, segments} | null
    horizon_quarters                     INTEGER NOT NULL DEFAULT 9
        CHECK (horizon_quarters BETWEEN 1 AND 9),
    translation_table_version              VARCHAR NOT NULL
        REFERENCES scenario.scenario_translation_table (version),
    regulatory_parameter_version             VARCHAR NOT NULL,
    classification                             VARCHAR NOT NULL
        CHECK (classification IN ('SUPERVISORY', 'EXPLORATORY')),
    status                                       VARCHAR NOT NULL DEFAULT 'DRAFT'
        CHECK (status IN ('DRAFT', 'NEEDS_CLARIFICATION', 'CONFIRMED', 'EXECUTED', 'REJECTED')),
    requested_by                                   VARCHAR NOT NULL,
    confirmed_by                                     VARCHAR,
    confirmed_at                                       TIMESTAMP,
    created_at                                           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scenario.scenario_run_result (
    scenario_run_id          VARCHAR PRIMARY KEY,   -- uuid
    scenario_spec_id           VARCHAR NOT NULL REFERENCES scenario.scenario_spec (scenario_spec_id),
    base_pipeline_run_id         VARCHAR NOT NULL,
    input_hash                     VARCHAR NOT NULL,
    stress_engine_version             VARCHAR NOT NULL,
    translation_table_version           VARCHAR NOT NULL
        REFERENCES scenario.scenario_translation_table (version),
    regulatory_parameter_version           VARCHAR NOT NULL,
    classification                           VARCHAR NOT NULL
        CHECK (classification IN ('SUPERVISORY', 'EXPLORATORY')),
    projected_loss_9q                          DECIMAL(22, 2),  -- illustrative, see design doc §3.18
    created_at                                   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scenario.stressed_loan_metrics (
    scenario_run_id          VARCHAR NOT NULL
        REFERENCES scenario.scenario_run_result (scenario_run_id),
    loan_id                     VARCHAR NOT NULL,
    quarter                       INTEGER NOT NULL CHECK (quarter BETWEEN 1 AND 9),
    pd_stressed                    DECIMAL(5, 4),
    lgd_stressed                     DECIMAL(5, 4),
    ccf_stressed                       DECIMAL(5, 4),
    ead_stressed                         DECIMAL(18, 2),
    el_stressed                           DECIMAL(18, 2),
    rwa_stressed                            DECIMAL(18, 2),
    PRIMARY KEY (scenario_run_id, loan_id, quarter)
);

-- Baseline vs. stressed comparison rows, aggregated by quarter x segment x
-- grade (the Scenario Comparison view's data source — see requirements.md
-- AG-3.6, 02-design-document.md §2.10 ScenarioRunResult.rows).
CREATE TABLE IF NOT EXISTS scenario.scenario_comparison (
    scenario_run_id          VARCHAR NOT NULL
        REFERENCES scenario.scenario_run_result (scenario_run_id),
    quarter                     INTEGER NOT NULL CHECK (quarter BETWEEN 1 AND 9),
    portfolio_segment             VARCHAR NOT NULL,
    credit_rating_grade             INTEGER NOT NULL,
    ead_base                          DECIMAL(22, 2) NOT NULL,
    ead_stressed                        DECIMAL(22, 2) NOT NULL,
    el_base                               DECIMAL(22, 2) NOT NULL,
    el_stressed                             DECIMAL(22, 2) NOT NULL,
    rwa_base                                  DECIMAL(22, 2) NOT NULL,
    rwa_stressed                                DECIMAL(22, 2) NOT NULL,
    loan_count                                    INTEGER NOT NULL,
    PRIMARY KEY (scenario_run_id, quarter, portfolio_segment, credit_rating_grade)
);
