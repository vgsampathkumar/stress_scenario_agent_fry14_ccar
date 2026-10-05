-- Quarantine Repository: records that failed contract validation, isolated
-- with reason codes so the valid-record stream is never blocked.
-- PII fields are hashed before landing here — see 02-design-document.md §2.3, §3.3.

CREATE TABLE IF NOT EXISTS quarantine.quarantine_record (
    quarantine_id            UUID PRIMARY KEY,
    loan_id                   VARCHAR NOT NULL,
    pipeline_run_id           VARCHAR NOT NULL,
    contract_id               VARCHAR NOT NULL,
    contract_version          VARCHAR NOT NULL,
    original_record           JSON NOT NULL,        -- full record, PII fields pre-hashed
    exception_reason_codes    JSON NOT NULL,         -- array of reason codes, e.g. ["NEGATIVE_BALANCE"]
    rejected_at                TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    remediation_status         VARCHAR NOT NULL DEFAULT 'OPEN'
        CHECK (remediation_status IN ('OPEN', 'IN_REVIEW', 'RESOLVED', 'WONT_FIX'))
);

CREATE INDEX IF NOT EXISTS idx_quarantine_run_id ON quarantine.quarantine_record (pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_quarantine_status ON quarantine.quarantine_record (remediation_status);
