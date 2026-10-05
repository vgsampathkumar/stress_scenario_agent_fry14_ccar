-- Logical zone separation (see 02-design-document.md §1 component inventory).
-- Each zone is a separate schema/namespace within the single local store (DuckDB),
-- so migrating a zone to its own physical platform later needs no redesign.

CREATE SCHEMA IF NOT EXISTS landing;
CREATE SCHEMA IF NOT EXISTS quarantine;
CREATE SCHEMA IF NOT EXISTS governed;
CREATE SCHEMA IF NOT EXISTS metrics;
CREATE SCHEMA IF NOT EXISTS aggregates;
CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS reference;
CREATE SCHEMA IF NOT EXISTS rbac;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS contracts;

-- v2.0 agentic-layer zones (see 02-design-document.md §1, C17-C31).
CREATE SCHEMA IF NOT EXISTS scenario;
CREATE SCHEMA IF NOT EXISTS agent_governance;
