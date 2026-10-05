-- Contract Registry: versioned data contracts (schema + business rules).
-- See 02-design-document.md §2.2, §3.2.

CREATE TABLE IF NOT EXISTS contracts.data_contract (
    contract_id       VARCHAR NOT NULL,
    version           VARCHAR NOT NULL,          -- semver, e.g. "1.0.0"
    effective_date    DATE NOT NULL,
    definition        JSON NOT NULL,              -- full DataContract document (fields + business_rules)
    published_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_by      VARCHAR,
    PRIMARY KEY (contract_id, version)
);

CREATE TABLE IF NOT EXISTS contracts.active_contract (
    contract_id       VARCHAR PRIMARY KEY,
    active_version    VARCHAR NOT NULL,
    activated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
