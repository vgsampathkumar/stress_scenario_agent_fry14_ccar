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
