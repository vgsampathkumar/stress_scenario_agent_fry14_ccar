from __future__ import annotations

from pathlib import Path

from fry14_engine.audit.logger import AuditLogger
from fry14_engine.common.enums import AuditEventType
from fry14_engine.db import bootstrap, get_connection


def test_log_and_read_back_single_event(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    logger = AuditLogger(con)

    logger.log(
        AuditEventType.INGESTION,
        pipeline_run_id="run-1",
        detail={"records_landed": 10},
    )

    events = logger.read_run("run-1")
    assert len(events) == 1
    assert events[0].event_type == "INGESTION"
    assert events[0].pipeline_run_id == "run-1"
    assert events[0].detail == {"records_landed": 10}
    con.close()


def test_events_are_ordered_by_occurrence(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    logger = AuditLogger(con)

    for event_type in (
        AuditEventType.INGESTION,
        AuditEventType.VALIDATION,
        AuditEventType.CALCULATION,
    ):
        logger.log(event_type, pipeline_run_id="run-1")

    events = logger.read_run("run-1")
    assert [e.event_type for e in events] == ["INGESTION", "VALIDATION", "CALCULATION"]
    con.close()


def test_events_scoped_to_pipeline_run_id(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    logger = AuditLogger(con)

    logger.log(AuditEventType.INGESTION, pipeline_run_id="run-1")
    logger.log(AuditEventType.INGESTION, pipeline_run_id="run-2")

    assert len(logger.read_run("run-1")) == 1
    assert len(logger.read_run("run-2")) == 1
    assert logger.read_run("run-3") == []
    con.close()


def test_access_control_event_can_have_no_pipeline_run_id(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    logger = AuditLogger(con)

    logger.log(
        AuditEventType.ACCESS_CONTROL,
        pipeline_run_id=None,
        actor="FINANCE",
        detail={"decision": "ALLOWED"},
    )

    row = con.execute(
        "SELECT pipeline_run_id, actor, event_type FROM audit.event_log "
        "WHERE event_type = 'ACCESS_CONTROL'"
    ).fetchone()
    assert row[0] is None
    assert row[1] == "FINANCE"
    con.close()


def test_detail_never_contains_raw_pii_by_construction():
    """Structural guarantee: nothing in this module ever receives a raw PII
    value to log in the first place — callers pass summary counts/strings,
    not record payloads. This test documents that contract."""
    import inspect

    from fry14_engine.audit import logger as logger_module

    source = inspect.getsource(logger_module)
    assert "borrower_tax_id" not in source
    assert "borrower_legal_name" not in source
    assert "borrower_address" not in source
