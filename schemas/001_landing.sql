-- Landing zone: immutable, append-only raw records as received from source
-- adapters, post metadata-stamping. No updates/deletes — corrections arrive
-- as new records under a new pipeline_run_id. See 02-design-document.md §2.1, §3.1.

CREATE TABLE IF NOT EXISTS landing.raw_loan_record (
    landing_id                  UUID PRIMARY KEY,
    loan_id                     VARCHAR NOT NULL,
    borrower_tax_id             VARCHAR,        -- RAW PII; hashed before any later zone persists it
    borrower_legal_name         VARCHAR,        -- RAW PII
    borrower_address            VARCHAR,        -- RAW PII
    counterparty_id             VARCHAR,
    asset_class                 VARCHAR,
    internal_credit_risk_grade  INTEGER,
    credit_score                INTEGER,
    outstanding_balance         DECIMAL(18, 2),
    unadvanced_commitment       DECIMAL(18, 2),
    origination_date            DATE,
    maturity_date                DATE,
    probability_of_default      DECIMAL(9, 6),
    loss_given_default          DECIMAL(9, 6),
    portfolio_segment           VARCHAR,
    source_system_of_record     VARCHAR,

    -- _ingestion_metadata envelope (flattened for columnar storage)
    ingestion_timestamp          TIMESTAMP NOT NULL,
    source_entity_code           VARCHAR NOT NULL,
    pipeline_run_id              VARCHAR NOT NULL,
    ingestion_channel            VARCHAR NOT NULL CHECK (ingestion_channel IN ('BATCH', 'EVENT')),

    landed_at                    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_landing_run_id ON landing.raw_loan_record (pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_landing_loan_id ON landing.raw_loan_record (loan_id);
