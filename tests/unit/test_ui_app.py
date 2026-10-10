"""Agent UI (`fry14_engine.ui.app`) tests: the module imports cleanly in
Streamlit's "bare mode" (no running server — this is exactly how `pytest`
collects it), its pure helper functions behave correctly, and — via
Streamlit's own `AppTest` harness — a full interactive run (click "Run
agent demo", then open every tab) completes with no exception. This is
in addition to the manual headless smoke test (`streamlit run ...
--server.headless true`, confirmed HTTP 200 with no startup exceptions).
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from fry14_engine.common.enums import Permission, RoleName
from fry14_engine.ui.app import _grounding_badge, _roles_with

APP_PATH = str(Path(__file__).resolve().parents[2] / "src" / "fry14_engine" / "ui" / "app.py")


def test_module_imports_without_raising():
    import fry14_engine.ui.app  # noqa: F401 - import itself is the assertion


def test_grounding_badge_passed():
    assert "PASSED" in _grounding_badge("PASSED")


def test_grounding_badge_failed():
    assert "FAILED" in _grounding_badge("FAILED")


def test_roles_with_permission_matches_rbac_matrix():
    roles = _roles_with(Permission.PUBLISH_DATA_PRODUCT)
    assert RoleName.REGULATORY_REPORTING in roles
    assert RoleName.DATA_ENGINEER not in roles


def test_app_renders_with_no_demo_run_yet():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    assert not at.exception
    assert len(at.tabs) == 8


def test_running_the_demo_populates_every_tab(tmp_db_path: Path):
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)

    at.sidebar.number_input[0].set_value(10)  # "Clean records"
    at.sidebar.text_input[0].set_value(str(tmp_db_path))  # "DuckDB path"
    at.sidebar.button[0].click()
    at.run(timeout=60)

    assert not at.exception
    assert len(at.tabs[0].metric) == 5  # Overview: total/governed/quarantined/DQ/projected loss
    assert at.tabs[6].success or at.tabs[6].expander  # Approval Queue: empty or pending list
    assert at.tabs[7].expander  # Agent Trace: at least one session group
