from __future__ import annotations

from pathlib import Path

from fry14_engine.db import bootstrap, get_connection

EXPECTED_TABLES = {
    "landing.raw_loan_record",
    "contracts.data_contract",
    "contracts.active_contract",
    "quarantine.quarantine_record",
    "governed.loan_record",
    "governed.pii_reidentification_vault",
    "reference.regulatory_parameter_set",
    "reference.credit_conversion_factor",
    "reference.risk_weight",
    "reference.asset_classification",
    "metrics.loan_risk_metrics",
    "metrics.calculation_exception",
    "aggregates.schedule_aggregate",
    "catalog.data_product_catalog_entry",
    "catalog.schema_version_history",
    "rbac.role",
    "rbac.role_permission",
    "rbac.user_role",
    "audit.event_log",
    "scenario.supervisory_scenario",
    "scenario.scenario_translation_table",
    "scenario.scenario_translation_entry",
    "scenario.scenario_translation_grade_sensitivity",
    "scenario.grade_pd_grid",
    "scenario.scenario_spec",
    "scenario.scenario_run_result",
    "scenario.stressed_loan_metrics",
    "scenario.scenario_comparison",
    "agent_governance.tool_policy",
    "agent_governance.tool_policy_condition",
    "agent_governance.agent_proposal",
    "agent_governance.agent_trace_event",
    "agent_governance.grounded_narrative",
}


def test_bootstrap_creates_all_expected_tables(tmp_db_path: Path):
    bootstrap(tmp_db_path)

    con = get_connection(tmp_db_path)
    try:
        rows = con.execute("""
            SELECT table_schema || '.' || table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('information_schema', 'main', 'pg_catalog')
            """).fetchall()
    finally:
        con.close()

    actual_tables = {row[0] for row in rows}
    assert EXPECTED_TABLES.issubset(actual_tables)


def test_bootstrap_is_idempotent(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    bootstrap(tmp_db_path)  # must not raise on re-run


def test_bootstrap_seeds_rbac_roles(tmp_db_path: Path):
    bootstrap(tmp_db_path)

    con = get_connection(tmp_db_path)
    try:
        count = con.execute("SELECT COUNT(*) FROM rbac.role").fetchone()[0]
    finally:
        con.close()

    assert count == 6
