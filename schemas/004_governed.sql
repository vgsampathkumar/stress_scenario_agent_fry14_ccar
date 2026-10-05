-- Governed zone: contract-valid, PII-hashed records ready for risk calculation.
-- See 02-design-document.md §2.4, §3.3.

-- Nullability here deliberately mirrors exactly what the active contract
-- (Phase 2) guarantees, not what a "complete" loan record would ideally
-- have. Fields the contract doesn't require non-null on (PII fields are
-- nullable=true; unadvanced_commitment/maturity_date/PD/LGD/portfolio_segment
-- have no non-null rule in v1.0.0) stay nullable here too — their absence
-- is a Phase 4/5 calculation-exception concern (e.g. CALC_MISSING_PD_LGD),
-- not a contract violation, so governance must not reject them.
CREATE TABLE IF NOT EXISTS governed.loan_record (
    governed_id                  UUID PRIMARY KEY,
    loan_id                       VARCHAR NOT NULL,
    borrower_key_hash             VARCHAR,            -- HMAC-SHA256(borrower_tax_id), null if absent
    borrower_name_hash            VARCHAR,
    borrower_address_hash         VARCHAR,
    counterparty_id               VARCHAR,
    asset_class                   VARCHAR NOT NULL,
    internal_credit_risk_grade    INTEGER NOT NULL,
    credit_score                  INTEGER NOT NULL,
    outstanding_balance           DECIMAL(18, 2) NOT NULL,
    unadvanced_commitment         DECIMAL(18, 2),
    maturity_date                  DATE,
    probability_of_default        DECIMAL(9, 6),
    loss_given_default            DECIMAL(9, 6),
    portfolio_segment             VARCHAR,

    pipeline_run_id                VARCHAR NOT NULL,
    contract_version               VARCHAR NOT NULL,
    ingestion_timestamp             TIMESTAMP NOT NULL,

    governed_at                     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_governed_run_id ON governed.loan_record (pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_governed_loan_id ON governed.loan_record (loan_id);

-- Re-identification vault: separate table, access gated at the application
-- layer by VIEW_RAW_PII permission only. Written at hash-time, read only by
-- Compliance/Audit via a distinct, fully-audited API path.
CREATE TABLE IF NOT EXISTS governed.pii_reidentification_vault (
    hash_value          VARCHAR PRIMARY KEY,
    encrypted_raw_value  VARCHAR NOT NULL,
    field_name            VARCHAR NOT NULL,   -- 'borrower_tax_id' | 'borrower_legal_name' | 'borrower_address'
    hash_key_version      VARCHAR NOT NULL,
    created_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
