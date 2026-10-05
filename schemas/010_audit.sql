-- Lineage & Audit Log: append-only event stream covering every stage of a
-- run plus every access-control decision. See 02-design-document.md §3.10.

CREATE TABLE IF NOT EXISTS audit.event_log (
    event_id         UUID PRIMARY KEY,
    pipeline_run_id    VARCHAR,
    event_type           VARCHAR NOT NULL,  -- e.g. INGESTION, VALIDATION, PII_HASH, CALCULATION,
                                              -- AGGREGATION, CATALOG_UPDATE, ACCESS_CONTROL
    actor                  VARCHAR,            -- user/service identity, where applicable
    detail                   JSON,              -- event-specific payload (never raw PII)
    occurred_at                TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_run_id ON audit.event_log (pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit.event_log (event_type);
