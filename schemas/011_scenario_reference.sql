-- Scenario Reference Store: Fed supervisory scenarios, scenario translation
-- tables, and grade PD grids (versioned, approval-gated reference data).
-- See 02-design-document.md §1 (C27), §2.10.

CREATE TABLE IF NOT EXISTS scenario.supervisory_scenario (
    scenario_version   VARCHAR NOT NULL,          -- e.g. 'FED-2026'
    scenario_name       VARCHAR NOT NULL
        CHECK (scenario_name IN ('BASELINE', 'SEVERELY_ADVERSE')),
    quarter              INTEGER NOT NULL CHECK (quarter BETWEEN 0 AND 9),
    macro_variable        VARCHAR NOT NULL
        CHECK (macro_variable IN ('UNEMPLOYMENT_RATE', 'REAL_GDP_GROWTH',
                                   'CRE_PRICE_INDEX', 'HOUSE_PRICE_INDEX',
                                   'TREASURY_3M', 'TREASURY_10Y', 'BBB_CORPORATE_YIELD')),
    value                  DECIMAL(10, 4) NOT NULL,
    PRIMARY KEY (scenario_version, scenario_name, quarter, macro_variable)
);

CREATE TABLE IF NOT EXISTS scenario.scenario_translation_table (
    version              VARCHAR PRIMARY KEY,      -- semver
    effective_date        DATE NOT NULL,
    status                  VARCHAR NOT NULL CHECK (status IN ('DRAFT', 'APPROVED')),
    approved_by             VARCHAR,
    multiplier_floor        DECIMAL(5, 4) NOT NULL,
    multiplier_cap           DECIMAL(5, 4) NOT NULL,
    methodology_note          VARCHAR,
    created_at                TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scenario.scenario_translation_entry (
    version              VARCHAR NOT NULL
        REFERENCES scenario.scenario_translation_table (version),
    portfolio_segment      VARCHAR NOT NULL,
    asset_class              VARCHAR NOT NULL,
    target                    VARCHAR NOT NULL CHECK (target IN ('PD', 'LGD', 'DRAWDOWN')),
    macro_variable             VARCHAR NOT NULL
        CHECK (macro_variable IN ('UNEMPLOYMENT_RATE', 'REAL_GDP_GROWTH',
                                   'CRE_PRICE_INDEX', 'HOUSE_PRICE_INDEX',
                                   'TREASURY_3M', 'TREASURY_10Y', 'BBB_CORPORATE_YIELD')),
    beta                        DECIMAL(10, 6) NOT NULL,
    transform                    VARCHAR NOT NULL CHECK (transform IN ('LEVEL_CHANGE', 'PCT_CHANGE')),
    PRIMARY KEY (version, portfolio_segment, asset_class, target, macro_variable)
);

CREATE TABLE IF NOT EXISTS scenario.scenario_translation_grade_sensitivity (
    version              VARCHAR NOT NULL
        REFERENCES scenario.scenario_translation_table (version),
    grade                   INTEGER NOT NULL CHECK (grade BETWEEN 1 AND 10),
    pd_scaling               DECIMAL(10, 6) NOT NULL,
    PRIMARY KEY (version, grade)
);

CREATE TABLE IF NOT EXISTS scenario.grade_pd_grid (
    version              VARCHAR NOT NULL,
    grade                   INTEGER NOT NULL CHECK (grade BETWEEN 1 AND 10),
    pd                        DECIMAL(5, 4) NOT NULL CHECK (pd >= 0 AND pd <= 1),
    PRIMARY KEY (version, grade)
);

-- Illustrative seed data (v1.0.0 / FED-2026) — synthetic, NOT calibrated to
-- any actual Federal Reserve release. Seeded the same idempotent way
-- schemas/005_reference_data.sql and schemas/009_rbac.sql seed their
-- reference data. See 01-approach-paper.md §8 assumptions.

-- Supervisory scenarios: 10 quarters (0 = jump-off, 1-9 = projection) x 7
-- macro variables x 2 scenarios. Severely Adverse models a sharp
-- unemployment spike, GDP contraction, CRE/HPI price declines, and a
-- flight-to-safety rate move with credit-spread widening; Baseline is
-- mild and roughly flat.
INSERT INTO scenario.supervisory_scenario (scenario_version, scenario_name, quarter, macro_variable, value)
SELECT * FROM (VALUES
    -- BASELINE: UNEMPLOYMENT_RATE
    ('FED-2026', 'BASELINE', 0, 'UNEMPLOYMENT_RATE', 4.0),
    ('FED-2026', 'BASELINE', 1, 'UNEMPLOYMENT_RATE', 4.0),
    ('FED-2026', 'BASELINE', 2, 'UNEMPLOYMENT_RATE', 4.0),
    ('FED-2026', 'BASELINE', 3, 'UNEMPLOYMENT_RATE', 4.1),
    ('FED-2026', 'BASELINE', 4, 'UNEMPLOYMENT_RATE', 4.1),
    ('FED-2026', 'BASELINE', 5, 'UNEMPLOYMENT_RATE', 4.1),
    ('FED-2026', 'BASELINE', 6, 'UNEMPLOYMENT_RATE', 4.2),
    ('FED-2026', 'BASELINE', 7, 'UNEMPLOYMENT_RATE', 4.2),
    ('FED-2026', 'BASELINE', 8, 'UNEMPLOYMENT_RATE', 4.2),
    ('FED-2026', 'BASELINE', 9, 'UNEMPLOYMENT_RATE', 4.2),
    -- BASELINE: REAL_GDP_GROWTH
    ('FED-2026', 'BASELINE', 0, 'REAL_GDP_GROWTH', 2.0),
    ('FED-2026', 'BASELINE', 1, 'REAL_GDP_GROWTH', 2.0),
    ('FED-2026', 'BASELINE', 2, 'REAL_GDP_GROWTH', 2.0),
    ('FED-2026', 'BASELINE', 3, 'REAL_GDP_GROWTH', 2.0),
    ('FED-2026', 'BASELINE', 4, 'REAL_GDP_GROWTH', 2.0),
    ('FED-2026', 'BASELINE', 5, 'REAL_GDP_GROWTH', 2.0),
    ('FED-2026', 'BASELINE', 6, 'REAL_GDP_GROWTH', 2.0),
    ('FED-2026', 'BASELINE', 7, 'REAL_GDP_GROWTH', 2.0),
    ('FED-2026', 'BASELINE', 8, 'REAL_GDP_GROWTH', 2.0),
    ('FED-2026', 'BASELINE', 9, 'REAL_GDP_GROWTH', 2.0),
    -- BASELINE: CRE_PRICE_INDEX
    ('FED-2026', 'BASELINE', 0, 'CRE_PRICE_INDEX', 100.0),
    ('FED-2026', 'BASELINE', 1, 'CRE_PRICE_INDEX', 101.0),
    ('FED-2026', 'BASELINE', 2, 'CRE_PRICE_INDEX', 102.0),
    ('FED-2026', 'BASELINE', 3, 'CRE_PRICE_INDEX', 103.0),
    ('FED-2026', 'BASELINE', 4, 'CRE_PRICE_INDEX', 104.0),
    ('FED-2026', 'BASELINE', 5, 'CRE_PRICE_INDEX', 105.0),
    ('FED-2026', 'BASELINE', 6, 'CRE_PRICE_INDEX', 106.0),
    ('FED-2026', 'BASELINE', 7, 'CRE_PRICE_INDEX', 107.0),
    ('FED-2026', 'BASELINE', 8, 'CRE_PRICE_INDEX', 108.0),
    ('FED-2026', 'BASELINE', 9, 'CRE_PRICE_INDEX', 109.0),
    -- BASELINE: HOUSE_PRICE_INDEX
    ('FED-2026', 'BASELINE', 0, 'HOUSE_PRICE_INDEX', 100.0),
    ('FED-2026', 'BASELINE', 1, 'HOUSE_PRICE_INDEX', 100.8),
    ('FED-2026', 'BASELINE', 2, 'HOUSE_PRICE_INDEX', 101.6),
    ('FED-2026', 'BASELINE', 3, 'HOUSE_PRICE_INDEX', 102.4),
    ('FED-2026', 'BASELINE', 4, 'HOUSE_PRICE_INDEX', 103.2),
    ('FED-2026', 'BASELINE', 5, 'HOUSE_PRICE_INDEX', 104.0),
    ('FED-2026', 'BASELINE', 6, 'HOUSE_PRICE_INDEX', 104.8),
    ('FED-2026', 'BASELINE', 7, 'HOUSE_PRICE_INDEX', 105.6),
    ('FED-2026', 'BASELINE', 8, 'HOUSE_PRICE_INDEX', 106.4),
    ('FED-2026', 'BASELINE', 9, 'HOUSE_PRICE_INDEX', 107.2),
    -- BASELINE: TREASURY_3M
    ('FED-2026', 'BASELINE', 0, 'TREASURY_3M', 4.5),
    ('FED-2026', 'BASELINE', 1, 'TREASURY_3M', 4.5),
    ('FED-2026', 'BASELINE', 2, 'TREASURY_3M', 4.5),
    ('FED-2026', 'BASELINE', 3, 'TREASURY_3M', 4.5),
    ('FED-2026', 'BASELINE', 4, 'TREASURY_3M', 4.5),
    ('FED-2026', 'BASELINE', 5, 'TREASURY_3M', 4.5),
    ('FED-2026', 'BASELINE', 6, 'TREASURY_3M', 4.5),
    ('FED-2026', 'BASELINE', 7, 'TREASURY_3M', 4.5),
    ('FED-2026', 'BASELINE', 8, 'TREASURY_3M', 4.5),
    ('FED-2026', 'BASELINE', 9, 'TREASURY_3M', 4.5),
    -- BASELINE: TREASURY_10Y
    ('FED-2026', 'BASELINE', 0, 'TREASURY_10Y', 4.3),
    ('FED-2026', 'BASELINE', 1, 'TREASURY_10Y', 4.3),
    ('FED-2026', 'BASELINE', 2, 'TREASURY_10Y', 4.3),
    ('FED-2026', 'BASELINE', 3, 'TREASURY_10Y', 4.3),
    ('FED-2026', 'BASELINE', 4, 'TREASURY_10Y', 4.3),
    ('FED-2026', 'BASELINE', 5, 'TREASURY_10Y', 4.3),
    ('FED-2026', 'BASELINE', 6, 'TREASURY_10Y', 4.3),
    ('FED-2026', 'BASELINE', 7, 'TREASURY_10Y', 4.3),
    ('FED-2026', 'BASELINE', 8, 'TREASURY_10Y', 4.3),
    ('FED-2026', 'BASELINE', 9, 'TREASURY_10Y', 4.3),
    -- BASELINE: BBB_CORPORATE_YIELD
    ('FED-2026', 'BASELINE', 0, 'BBB_CORPORATE_YIELD', 5.5),
    ('FED-2026', 'BASELINE', 1, 'BBB_CORPORATE_YIELD', 5.5),
    ('FED-2026', 'BASELINE', 2, 'BBB_CORPORATE_YIELD', 5.5),
    ('FED-2026', 'BASELINE', 3, 'BBB_CORPORATE_YIELD', 5.5),
    ('FED-2026', 'BASELINE', 4, 'BBB_CORPORATE_YIELD', 5.5),
    ('FED-2026', 'BASELINE', 5, 'BBB_CORPORATE_YIELD', 5.5),
    ('FED-2026', 'BASELINE', 6, 'BBB_CORPORATE_YIELD', 5.5),
    ('FED-2026', 'BASELINE', 7, 'BBB_CORPORATE_YIELD', 5.5),
    ('FED-2026', 'BASELINE', 8, 'BBB_CORPORATE_YIELD', 5.5),
    ('FED-2026', 'BASELINE', 9, 'BBB_CORPORATE_YIELD', 5.5),
    -- SEVERELY_ADVERSE: UNEMPLOYMENT_RATE
    ('FED-2026', 'SEVERELY_ADVERSE', 0, 'UNEMPLOYMENT_RATE', 4.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 1, 'UNEMPLOYMENT_RATE', 5.5),
    ('FED-2026', 'SEVERELY_ADVERSE', 2, 'UNEMPLOYMENT_RATE', 7.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 3, 'UNEMPLOYMENT_RATE', 8.5),
    ('FED-2026', 'SEVERELY_ADVERSE', 4, 'UNEMPLOYMENT_RATE', 9.8),
    ('FED-2026', 'SEVERELY_ADVERSE', 5, 'UNEMPLOYMENT_RATE', 10.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 6, 'UNEMPLOYMENT_RATE', 9.5),
    ('FED-2026', 'SEVERELY_ADVERSE', 7, 'UNEMPLOYMENT_RATE', 8.8),
    ('FED-2026', 'SEVERELY_ADVERSE', 8, 'UNEMPLOYMENT_RATE', 8.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 9, 'UNEMPLOYMENT_RATE', 7.5),
    -- SEVERELY_ADVERSE: REAL_GDP_GROWTH
    ('FED-2026', 'SEVERELY_ADVERSE', 0, 'REAL_GDP_GROWTH', 2.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 1, 'REAL_GDP_GROWTH', -3.5),
    ('FED-2026', 'SEVERELY_ADVERSE', 2, 'REAL_GDP_GROWTH', -4.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 3, 'REAL_GDP_GROWTH', -2.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 4, 'REAL_GDP_GROWTH', 0.5),
    ('FED-2026', 'SEVERELY_ADVERSE', 5, 'REAL_GDP_GROWTH', 1.5),
    ('FED-2026', 'SEVERELY_ADVERSE', 6, 'REAL_GDP_GROWTH', 2.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 7, 'REAL_GDP_GROWTH', 2.2),
    ('FED-2026', 'SEVERELY_ADVERSE', 8, 'REAL_GDP_GROWTH', 2.3),
    ('FED-2026', 'SEVERELY_ADVERSE', 9, 'REAL_GDP_GROWTH', 2.4),
    -- SEVERELY_ADVERSE: CRE_PRICE_INDEX
    ('FED-2026', 'SEVERELY_ADVERSE', 0, 'CRE_PRICE_INDEX', 100.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 1, 'CRE_PRICE_INDEX', 92.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 2, 'CRE_PRICE_INDEX', 85.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 3, 'CRE_PRICE_INDEX', 78.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 4, 'CRE_PRICE_INDEX', 72.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 5, 'CRE_PRICE_INDEX', 70.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 6, 'CRE_PRICE_INDEX', 71.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 7, 'CRE_PRICE_INDEX', 73.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 8, 'CRE_PRICE_INDEX', 76.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 9, 'CRE_PRICE_INDEX', 79.0),
    -- SEVERELY_ADVERSE: HOUSE_PRICE_INDEX
    ('FED-2026', 'SEVERELY_ADVERSE', 0, 'HOUSE_PRICE_INDEX', 100.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 1, 'HOUSE_PRICE_INDEX', 94.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 2, 'HOUSE_PRICE_INDEX', 88.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 3, 'HOUSE_PRICE_INDEX', 82.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 4, 'HOUSE_PRICE_INDEX', 77.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 5, 'HOUSE_PRICE_INDEX', 75.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 6, 'HOUSE_PRICE_INDEX', 76.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 7, 'HOUSE_PRICE_INDEX', 78.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 8, 'HOUSE_PRICE_INDEX', 80.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 9, 'HOUSE_PRICE_INDEX', 83.0),
    -- SEVERELY_ADVERSE: TREASURY_3M
    ('FED-2026', 'SEVERELY_ADVERSE', 0, 'TREASURY_3M', 4.5),
    ('FED-2026', 'SEVERELY_ADVERSE', 1, 'TREASURY_3M', 3.5),
    ('FED-2026', 'SEVERELY_ADVERSE', 2, 'TREASURY_3M', 2.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 3, 'TREASURY_3M', 1.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 4, 'TREASURY_3M', 0.5),
    ('FED-2026', 'SEVERELY_ADVERSE', 5, 'TREASURY_3M', 0.5),
    ('FED-2026', 'SEVERELY_ADVERSE', 6, 'TREASURY_3M', 0.5),
    ('FED-2026', 'SEVERELY_ADVERSE', 7, 'TREASURY_3M', 0.75),
    ('FED-2026', 'SEVERELY_ADVERSE', 8, 'TREASURY_3M', 1.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 9, 'TREASURY_3M', 1.25),
    -- SEVERELY_ADVERSE: TREASURY_10Y
    ('FED-2026', 'SEVERELY_ADVERSE', 0, 'TREASURY_10Y', 4.3),
    ('FED-2026', 'SEVERELY_ADVERSE', 1, 'TREASURY_10Y', 3.8),
    ('FED-2026', 'SEVERELY_ADVERSE', 2, 'TREASURY_10Y', 3.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 3, 'TREASURY_10Y', 2.3),
    ('FED-2026', 'SEVERELY_ADVERSE', 4, 'TREASURY_10Y', 2.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 5, 'TREASURY_10Y', 2.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 6, 'TREASURY_10Y', 2.1),
    ('FED-2026', 'SEVERELY_ADVERSE', 7, 'TREASURY_10Y', 2.3),
    ('FED-2026', 'SEVERELY_ADVERSE', 8, 'TREASURY_10Y', 2.5),
    ('FED-2026', 'SEVERELY_ADVERSE', 9, 'TREASURY_10Y', 2.7),
    -- SEVERELY_ADVERSE: BBB_CORPORATE_YIELD
    ('FED-2026', 'SEVERELY_ADVERSE', 0, 'BBB_CORPORATE_YIELD', 5.5),
    ('FED-2026', 'SEVERELY_ADVERSE', 1, 'BBB_CORPORATE_YIELD', 6.5),
    ('FED-2026', 'SEVERELY_ADVERSE', 2, 'BBB_CORPORATE_YIELD', 7.5),
    ('FED-2026', 'SEVERELY_ADVERSE', 3, 'BBB_CORPORATE_YIELD', 8.2),
    ('FED-2026', 'SEVERELY_ADVERSE', 4, 'BBB_CORPORATE_YIELD', 8.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 5, 'BBB_CORPORATE_YIELD', 7.5),
    ('FED-2026', 'SEVERELY_ADVERSE', 6, 'BBB_CORPORATE_YIELD', 7.0),
    ('FED-2026', 'SEVERELY_ADVERSE', 7, 'BBB_CORPORATE_YIELD', 6.7),
    ('FED-2026', 'SEVERELY_ADVERSE', 8, 'BBB_CORPORATE_YIELD', 6.5),
    ('FED-2026', 'SEVERELY_ADVERSE', 9, 'BBB_CORPORATE_YIELD', 6.3)
) AS v(scenario_version, scenario_name, quarter, macro_variable, value)
WHERE NOT EXISTS (
    SELECT 1 FROM scenario.supervisory_scenario
    WHERE scenario_version = v.scenario_version AND scenario_name = v.scenario_name
      AND quarter = v.quarter AND macro_variable = v.macro_variable
);

-- Scenario translation table v1.0.0 (APPROVED — four-eyes sign-off is a
-- human/process step this illustrative seed stands in for).
INSERT INTO scenario.scenario_translation_table
    (version, effective_date, status, approved_by, multiplier_floor, multiplier_cap, methodology_note)
SELECT * FROM (VALUES (
    '1.0.0', DATE '2026-01-01', 'APPROVED', 'risk.methodology@example.com', 0.5, 5.0,
    'Illustrative linear sensitivity table for demonstration purposes only. '
    'Betas are not calibrated to any institution''s actual loss experience or '
    'an approved econometric model; see 01-approach-paper.md §7 decision 11.'
)) AS v(version, effective_date, status, approved_by, multiplier_floor, multiplier_cap, methodology_note)
WHERE NOT EXISTS (SELECT 1 FROM scenario.scenario_translation_table WHERE version = '1.0.0');

-- PD driven by unemployment (level, pp), GDP growth (level, pp — beta
-- negative since a GDP *decline* should raise PD), and BBB spread (level,
-- pp). LGD driven by CRE price for the CRE book (pct change — beta
-- negative since a price *decline* should raise LGD) and BBB spread for
-- C&I (weaker recovery prospects in a credit crunch). DRAWDOWN driven by
-- unemployment (revolver utilization rises in a downturn).
INSERT INTO scenario.scenario_translation_entry
    (version, portfolio_segment, asset_class, target, macro_variable, beta, transform)
SELECT * FROM (VALUES
    -- PD x UNEMPLOYMENT_RATE
    ('1.0.0', 'SMALL_BUSINESS',   'CRE', 'PD', 'UNEMPLOYMENT_RATE', 0.35, 'LEVEL_CHANGE'),
    ('1.0.0', 'SMALL_BUSINESS',   'C&I', 'PD', 'UNEMPLOYMENT_RATE', 0.35, 'LEVEL_CHANGE'),
    ('1.0.0', 'MIDDLE_MARKET',    'CRE', 'PD', 'UNEMPLOYMENT_RATE', 0.20, 'LEVEL_CHANGE'),
    ('1.0.0', 'MIDDLE_MARKET',    'C&I', 'PD', 'UNEMPLOYMENT_RATE', 0.20, 'LEVEL_CHANGE'),
    ('1.0.0', 'LARGE_CORPORATE',  'CRE', 'PD', 'UNEMPLOYMENT_RATE', 0.10, 'LEVEL_CHANGE'),
    ('1.0.0', 'LARGE_CORPORATE',  'C&I', 'PD', 'UNEMPLOYMENT_RATE', 0.10, 'LEVEL_CHANGE'),
    -- PD x REAL_GDP_GROWTH
    ('1.0.0', 'SMALL_BUSINESS',   'CRE', 'PD', 'REAL_GDP_GROWTH', -0.08, 'LEVEL_CHANGE'),
    ('1.0.0', 'SMALL_BUSINESS',   'C&I', 'PD', 'REAL_GDP_GROWTH', -0.08, 'LEVEL_CHANGE'),
    ('1.0.0', 'MIDDLE_MARKET',    'CRE', 'PD', 'REAL_GDP_GROWTH', -0.05, 'LEVEL_CHANGE'),
    ('1.0.0', 'MIDDLE_MARKET',    'C&I', 'PD', 'REAL_GDP_GROWTH', -0.05, 'LEVEL_CHANGE'),
    ('1.0.0', 'LARGE_CORPORATE',  'CRE', 'PD', 'REAL_GDP_GROWTH', -0.03, 'LEVEL_CHANGE'),
    ('1.0.0', 'LARGE_CORPORATE',  'C&I', 'PD', 'REAL_GDP_GROWTH', -0.03, 'LEVEL_CHANGE'),
    -- PD x BBB_CORPORATE_YIELD
    ('1.0.0', 'SMALL_BUSINESS',   'CRE', 'PD', 'BBB_CORPORATE_YIELD', 0.06, 'LEVEL_CHANGE'),
    ('1.0.0', 'SMALL_BUSINESS',   'C&I', 'PD', 'BBB_CORPORATE_YIELD', 0.06, 'LEVEL_CHANGE'),
    ('1.0.0', 'MIDDLE_MARKET',    'CRE', 'PD', 'BBB_CORPORATE_YIELD', 0.04, 'LEVEL_CHANGE'),
    ('1.0.0', 'MIDDLE_MARKET',    'C&I', 'PD', 'BBB_CORPORATE_YIELD', 0.04, 'LEVEL_CHANGE'),
    ('1.0.0', 'LARGE_CORPORATE',  'CRE', 'PD', 'BBB_CORPORATE_YIELD', 0.02, 'LEVEL_CHANGE'),
    ('1.0.0', 'LARGE_CORPORATE',  'C&I', 'PD', 'BBB_CORPORATE_YIELD', 0.02, 'LEVEL_CHANGE'),
    -- LGD x CRE_PRICE_INDEX (CRE book only)
    ('1.0.0', 'SMALL_BUSINESS',   'CRE', 'LGD', 'CRE_PRICE_INDEX', -0.50, 'PCT_CHANGE'),
    ('1.0.0', 'MIDDLE_MARKET',    'CRE', 'LGD', 'CRE_PRICE_INDEX', -0.40, 'PCT_CHANGE'),
    ('1.0.0', 'LARGE_CORPORATE',  'CRE', 'LGD', 'CRE_PRICE_INDEX', -0.30, 'PCT_CHANGE'),
    -- LGD x BBB_CORPORATE_YIELD (C&I book only)
    ('1.0.0', 'SMALL_BUSINESS',   'C&I', 'LGD', 'BBB_CORPORATE_YIELD', 0.03, 'LEVEL_CHANGE'),
    ('1.0.0', 'MIDDLE_MARKET',    'C&I', 'LGD', 'BBB_CORPORATE_YIELD', 0.03, 'LEVEL_CHANGE'),
    ('1.0.0', 'LARGE_CORPORATE',  'C&I', 'LGD', 'BBB_CORPORATE_YIELD', 0.03, 'LEVEL_CHANGE'),
    -- DRAWDOWN x UNEMPLOYMENT_RATE
    ('1.0.0', 'SMALL_BUSINESS',   'CRE', 'DRAWDOWN', 'UNEMPLOYMENT_RATE', 0.010, 'LEVEL_CHANGE'),
    ('1.0.0', 'SMALL_BUSINESS',   'C&I', 'DRAWDOWN', 'UNEMPLOYMENT_RATE', 0.010, 'LEVEL_CHANGE'),
    ('1.0.0', 'MIDDLE_MARKET',    'CRE', 'DRAWDOWN', 'UNEMPLOYMENT_RATE', 0.008, 'LEVEL_CHANGE'),
    ('1.0.0', 'MIDDLE_MARKET',    'C&I', 'DRAWDOWN', 'UNEMPLOYMENT_RATE', 0.008, 'LEVEL_CHANGE'),
    ('1.0.0', 'LARGE_CORPORATE',  'CRE', 'DRAWDOWN', 'UNEMPLOYMENT_RATE', 0.005, 'LEVEL_CHANGE'),
    ('1.0.0', 'LARGE_CORPORATE',  'C&I', 'DRAWDOWN', 'UNEMPLOYMENT_RATE', 0.005, 'LEVEL_CHANGE')
) AS v(version, portfolio_segment, asset_class, target, macro_variable, beta, transform)
WHERE NOT EXISTS (
    SELECT 1 FROM scenario.scenario_translation_entry
    WHERE version = v.version AND portfolio_segment = v.portfolio_segment
      AND asset_class = v.asset_class AND target = v.target AND macro_variable = v.macro_variable
);

-- Grade sensitivity: worse grades scale shocks up, better grades scale
-- them down. Linear from 0.5 (grade 1) to 2.0 (grade 10).
INSERT INTO scenario.scenario_translation_grade_sensitivity (version, grade, pd_scaling)
SELECT * FROM (VALUES
    ('1.0.0', 1, 0.500),
    ('1.0.0', 2, 0.667),
    ('1.0.0', 3, 0.833),
    ('1.0.0', 4, 1.000),
    ('1.0.0', 5, 1.167),
    ('1.0.0', 6, 1.333),
    ('1.0.0', 7, 1.500),
    ('1.0.0', 8, 1.667),
    ('1.0.0', 9, 1.833),
    ('1.0.0', 10, 2.000)
) AS v(version, grade, pd_scaling)
WHERE NOT EXISTS (
    SELECT 1 FROM scenario.scenario_translation_grade_sensitivity
    WHERE version = v.version AND grade = v.grade
);

-- Grade PD grid v1.0.0 (used only for grade-migration shocks): illustrative
-- standardized grade curve, each grade roughly double the prior.
INSERT INTO scenario.grade_pd_grid (version, grade, pd)
SELECT * FROM (VALUES
    ('1.0.0', 1, 0.0005),
    ('1.0.0', 2, 0.0010),
    ('1.0.0', 3, 0.0020),
    ('1.0.0', 4, 0.0040),
    ('1.0.0', 5, 0.0080),
    ('1.0.0', 6, 0.0150),
    ('1.0.0', 7, 0.0300),
    ('1.0.0', 8, 0.0600),
    ('1.0.0', 9, 0.1200),
    ('1.0.0', 10, 0.2000)
) AS v(version, grade, pd)
WHERE NOT EXISTS (
    SELECT 1 FROM scenario.grade_pd_grid WHERE version = v.version AND grade = v.grade
);
