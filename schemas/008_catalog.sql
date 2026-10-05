-- Data Product Catalog: operational health, DQ %, schema version history, SLA.
-- See 02-design-document.md §2.8, §3.7.

CREATE TABLE IF NOT EXISTS catalog.data_product_catalog_entry (
    data_product_id       VARCHAR PRIMARY KEY,
    health_score            DECIMAL(5, 2) NOT NULL,
    dq_pass_percentage        DECIMAL(5, 2) NOT NULL,
    sla_status                 VARCHAR NOT NULL CHECK (sla_status IN ('ON_TIME', 'AT_RISK', 'BREACHED')),
    last_run_id                  VARCHAR,
    last_updated_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    owner                          VARCHAR
);

CREATE TABLE IF NOT EXISTS catalog.schema_version_history (
    data_product_id       VARCHAR NOT NULL,
    version                  VARCHAR NOT NULL,
    effective_date             DATE NOT NULL,
    changelog                    VARCHAR,
    PRIMARY KEY (data_product_id, version)
);
