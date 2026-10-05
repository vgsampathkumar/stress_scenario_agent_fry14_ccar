-- RBAC: role/permission matrix. See 02-design-document.md §2.9, §3.9.

CREATE TABLE IF NOT EXISTS rbac.role (
    role_id        VARCHAR PRIMARY KEY,
    name             VARCHAR NOT NULL UNIQUE
        CHECK (name IN ('DATA_ENGINEER', 'FINANCE', 'RISK', 'REGULATORY_REPORTING',
                        'COMPLIANCE_AUDIT', 'ADMIN'))
);

CREATE TABLE IF NOT EXISTS rbac.role_permission (
    role_id        VARCHAR NOT NULL REFERENCES rbac.role (role_id),
    permission       VARCHAR NOT NULL,
    PRIMARY KEY (role_id, permission)
);

CREATE TABLE IF NOT EXISTS rbac.user_role (
    user_id        VARCHAR NOT NULL,
    role_id          VARCHAR NOT NULL REFERENCES rbac.role (role_id),
    assigned_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, role_id)
);

-- Seed roles (matrix is populated by application code at bootstrap time —
-- see src/fry14_engine/rbac — this table just defines the fixed role set).
INSERT INTO rbac.role (role_id, name)
SELECT * FROM (VALUES
    ('role_data_engineer', 'DATA_ENGINEER'),
    ('role_finance', 'FINANCE'),
    ('role_risk', 'RISK'),
    ('role_regulatory_reporting', 'REGULATORY_REPORTING'),
    ('role_compliance_audit', 'COMPLIANCE_AUDIT'),
    ('role_admin', 'ADMIN')
) AS v(role_id, name)
WHERE NOT EXISTS (SELECT 1 FROM rbac.role WHERE rbac.role.role_id = v.role_id);
