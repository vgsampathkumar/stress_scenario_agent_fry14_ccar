-- Reference Data Store: versioned regulatory parameter tables.
-- See 02-design-document.md §2.5, §3.4.

CREATE TABLE IF NOT EXISTS reference.regulatory_parameter_set (
    version           VARCHAR PRIMARY KEY,   -- semver
    effective_date    DATE NOT NULL,
    description        VARCHAR,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reference.credit_conversion_factor (
    parameter_version   VARCHAR NOT NULL REFERENCES reference.regulatory_parameter_set (version),
    asset_class          VARCHAR NOT NULL,
    commitment_type       VARCHAR NOT NULL,
    ccf                    DECIMAL(5, 4) NOT NULL CHECK (ccf >= 0 AND ccf <= 1),
    PRIMARY KEY (parameter_version, asset_class, commitment_type)
);

CREATE TABLE IF NOT EXISTS reference.risk_weight (
    parameter_version   VARCHAR NOT NULL REFERENCES reference.regulatory_parameter_set (version),
    asset_class          VARCHAR NOT NULL,
    risk_weight            DECIMAL(5, 4) NOT NULL CHECK (risk_weight >= 0),
    PRIMARY KEY (parameter_version, asset_class)
);

CREATE TABLE IF NOT EXISTS reference.asset_classification (
    asset_class          VARCHAR PRIMARY KEY,
    description            VARCHAR NOT NULL
);

-- Illustrative standardized-approach parameters (v1.0.0), seeded the same
-- idempotent way schemas/009_rbac.sql seeds roles. "STANDARD" is the only
-- commitment_type modeled in this phase — loan-level commitment-type
-- granularity (revolving vs. term, cancellable vs. not) isn't part of the
-- current data model; see 01-approach-paper.md §8 assumptions.
INSERT INTO reference.regulatory_parameter_set (version, effective_date, description)
SELECT * FROM (VALUES
    ('1.0.0', DATE '2026-01-01',
     'Illustrative standardized-approach parameters for demonstration purposes only; '
     'not calibrated to any specific regulatory filing or jurisdiction.')
) AS v(version, effective_date, description)
WHERE NOT EXISTS (
    SELECT 1 FROM reference.regulatory_parameter_set WHERE version = v.version
);

INSERT INTO reference.credit_conversion_factor (parameter_version, asset_class, commitment_type, ccf)
SELECT * FROM (VALUES
    ('1.0.0', 'CRE', 'STANDARD', 0.50),
    ('1.0.0', 'C&I', 'STANDARD', 0.20)
) AS v(parameter_version, asset_class, commitment_type, ccf)
WHERE NOT EXISTS (
    SELECT 1 FROM reference.credit_conversion_factor
    WHERE parameter_version = v.parameter_version
      AND asset_class = v.asset_class
      AND commitment_type = v.commitment_type
);

INSERT INTO reference.risk_weight (parameter_version, asset_class, risk_weight)
SELECT * FROM (VALUES
    ('1.0.0', 'CRE', 1.00),
    ('1.0.0', 'C&I', 1.00)
) AS v(parameter_version, asset_class, risk_weight)
WHERE NOT EXISTS (
    SELECT 1 FROM reference.risk_weight
    WHERE parameter_version = v.parameter_version AND asset_class = v.asset_class
);

INSERT INTO reference.asset_classification (asset_class, description)
SELECT * FROM (VALUES
    ('CRE', 'Commercial Real Estate'),
    ('C&I', 'Commercial & Industrial')
) AS v(asset_class, description)
WHERE NOT EXISTS (
    SELECT 1 FROM reference.asset_classification WHERE asset_class = v.asset_class
);
