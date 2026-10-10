"""Quarantine Store (C6) read/update tests — the read side didn't exist
before Phase 10 (AG-2 needs it to triage and reprocess). See
02-design-document.md §2.3, §3.2.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from fry14_engine.common.enums import RemediationStatus
from fry14_engine.db import bootstrap, get_connection
from fry14_engine.quarantine.models import QuarantineRecord
from fry14_engine.quarantine.store import QuarantineStore


def _record(quarantine_id: str, reason_codes=("NEGATIVE_BALANCE",)) -> QuarantineRecord:
    return QuarantineRecord(
        quarantine_id=quarantine_id,
        loan_id=f"LN-{quarantine_id}",
        pipeline_run_id="run-1",
        contract_id="commercial_loan",
        contract_version="1.0.0",
        original_record={"loan_id": f"LN-{quarantine_id}", "outstanding_balance": "-100.0"},
        exception_reason_codes=reason_codes,
        rejected_at=datetime(2026, 6, 1),
    )


@pytest.fixture
def store(tmp_db_path: Path) -> QuarantineStore:
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    return QuarantineStore(con)


def test_read_by_id_roundtrip(store: QuarantineStore):
    record = _record("22222222-2222-2222-2222-222222222222")
    store.write([record])
    read_back = store.read_by_id(record.quarantine_id)
    assert read_back.loan_id == record.loan_id
    assert read_back.exception_reason_codes == record.exception_reason_codes


def test_read_by_id_unknown_returns_none(store: QuarantineStore):
    assert store.read_by_id("33333333-3333-3333-3333-333333333333") is None


def test_read_all_returns_every_record(store: QuarantineStore):
    store.write(
        [
            _record("44444444-4444-4444-4444-444444444444"),
            _record("55555555-5555-5555-5555-555555555555"),
        ]
    )
    assert len(store.read_all()) == 2


def test_update_remediation_status_persists(store: QuarantineStore):
    record = _record("66666666-6666-6666-6666-666666666666")
    store.write([record])
    store.update_remediation_status(record.quarantine_id, RemediationStatus.RESOLVED)
    read_back = store.read_by_id(record.quarantine_id)
    assert read_back.remediation_status == RemediationStatus.RESOLVED


def test_read_open_by_reason_code_excludes_resolved(store: QuarantineStore):
    open_record = _record("77777777-7777-7777-7777-777777777777")
    resolved_record = _record("88888888-8888-8888-8888-888888888888")
    store.write([open_record, resolved_record])
    store.update_remediation_status(resolved_record.quarantine_id, RemediationStatus.RESOLVED)

    matches = store.read_open_by_reason_code("NEGATIVE_BALANCE")
    assert [r.quarantine_id for r in matches] == [open_record.quarantine_id]
