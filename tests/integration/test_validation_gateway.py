from __future__ import annotations

import json
from pathlib import Path

from fry14_engine.common.enums import IngestionChannel
from fry14_engine.common.ids import new_pipeline_run_id
from fry14_engine.common.metadata import MetadataStamper
from fry14_engine.contracts.registry import ContractRegistry
from fry14_engine.contracts.validation_gateway import ValidationGateway
from fry14_engine.db import bootstrap, get_connection
from fry14_engine.ingestion.models import RawLoanRecord
from fry14_engine.ingestion.stamped import StampedRecord
from fry14_engine.pii.governed_store import GovernedStore
from fry14_engine.pii.hashing_service import PIIHashingService
from fry14_engine.synthetic.generator import generate_loan_records

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_HASH_KEY = "integration-test-secret-key"


def _load_commercial_loan_contract():
    registry = ContractRegistry(REPO_ROOT / "config" / "contracts")
    return registry.get_active("commercial_loan")


def _stamp(raw_records: list[dict], pipeline_run_id: str, fixed_clock) -> list[StampedRecord]:
    stamper = MetadataStamper(
        pipeline_run_id=pipeline_run_id,
        source_entity_code="ENTITY_001",
        source_system_of_record="CORE_LOAN_SYSTEM",
        ingestion_channel=IngestionChannel.BATCH,
        clock=fixed_clock,
    )
    return [
        StampedRecord(record=RawLoanRecord.model_validate(r), metadata=stamper.build_metadata())
        for r in raw_records
    ]


def test_mixed_batch_routes_governed_and_quarantined(tmp_db_path: Path, fixed_clock):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    contract = _load_commercial_loan_contract()

    raw = generate_loan_records(count=40, bad_record_rate=0.25, seed=777)
    run_id = new_pipeline_run_id()
    stamped = _stamp(raw, run_id, fixed_clock)

    gateway = ValidationGateway(con, PIIHashingService(TEST_HASH_KEY))
    result = gateway.run(stamped, contract, run_id)

    assert result.total_count == 40
    assert result.governed_count + result.quarantined_count == 40
    assert result.quarantined_count > 0

    governed_row_count = con.execute(
        "SELECT COUNT(*) FROM governed.loan_record WHERE pipeline_run_id = ?", [run_id]
    ).fetchone()[0]
    quarantine_row_count = con.execute(
        "SELECT COUNT(*) FROM quarantine.quarantine_record WHERE pipeline_run_id = ?", [run_id]
    ).fetchone()[0]
    assert governed_row_count == result.governed_count
    assert quarantine_row_count == result.quarantined_count

    expected_codes = {
        "NEGATIVE_BALANCE",
        "MISSING_CREDIT_SCORE",
        "INVALID_CREDIT_GRADE",
        "NULL_MANDATORY_FIELD",
    }
    assert set(result.reason_code_counts.keys()).issubset(expected_codes)

    expected_pass_rate = result.governed_count / 40
    assert result.dq_pass_rate == expected_pass_rate
    con.close()


def test_governed_records_have_correctly_hashed_pii(tmp_db_path: Path, fixed_clock):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    contract = _load_commercial_loan_contract()

    raw = generate_loan_records(count=10, bad_record_rate=0.0, seed=42)
    run_id = new_pipeline_run_id()
    stamped = _stamp(raw, run_id, fixed_clock)
    hashing_service = PIIHashingService(TEST_HASH_KEY)

    gateway = ValidationGateway(con, hashing_service)
    gateway.run(stamped, contract, run_id)

    rows = con.execute(
        "SELECT loan_id, borrower_key_hash FROM governed.loan_record WHERE pipeline_run_id = ?",
        [run_id],
    ).fetchall()
    con.close()

    by_loan_id = {r["loan_id"]: r for r in raw}
    assert len(rows) == 10
    for loan_id, borrower_key_hash in rows:
        expected_hash = hashing_service.hash_value(by_loan_id[loan_id]["borrower_tax_id"])
        assert borrower_key_hash == expected_hash


def test_quarantine_stores_real_hashes_not_raw_pii_or_placeholders(tmp_db_path: Path, fixed_clock):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    contract = _load_commercial_loan_contract()

    raw = generate_loan_records(count=20, bad_record_rate=0.5, seed=321)
    run_id = new_pipeline_run_id()
    stamped = _stamp(raw, run_id, fixed_clock)
    hashing_service = PIIHashingService(TEST_HASH_KEY)

    gateway = ValidationGateway(con, hashing_service)
    gateway.run(stamped, contract, run_id)

    rows = con.execute(
        "SELECT original_record FROM quarantine.quarantine_record WHERE pipeline_run_id = ?",
        [run_id],
    ).fetchall()
    con.close()

    assert rows
    raw_ssns = {r["borrower_tax_id"] for r in raw}
    for (original_record_json,) in rows:
        payload = json.loads(original_record_json)
        tax_id_value = payload.get("borrower_tax_id")
        assert tax_id_value not in raw_ssns
        assert tax_id_value != "<REDACTED-PENDING-PHASE-3-HASHING>"
        assert tax_id_value == hashing_service.hash_value(
            next(r["borrower_tax_id"] for r in raw if r["loan_id"] == payload["loan_id"])
        )


def test_no_raw_pii_anywhere_in_persisted_stores(tmp_db_path: Path, fixed_clock):
    """Automated scan: no raw SSN/name/address value from the input batch
    appears verbatim in either governed.loan_record or
    quarantine.quarantine_record."""
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    contract = _load_commercial_loan_contract()

    raw = generate_loan_records(count=30, bad_record_rate=0.3, seed=55)
    run_id = new_pipeline_run_id()
    stamped = _stamp(raw, run_id, fixed_clock)

    gateway = ValidationGateway(con, PIIHashingService(TEST_HASH_KEY))
    gateway.run(stamped, contract, run_id)

    governed_rows = con.execute(
        "SELECT * FROM governed.loan_record WHERE pipeline_run_id = ?", [run_id]
    ).fetchall()
    quarantine_rows = con.execute(
        "SELECT * FROM quarantine.quarantine_record WHERE pipeline_run_id = ?", [run_id]
    ).fetchall()
    con.close()

    raw_pii_values = set()
    for r in raw:
        for field_name in ("borrower_tax_id", "borrower_legal_name", "borrower_address"):
            if r.get(field_name):
                raw_pii_values.add(str(r[field_name]))

    all_text = "\n".join(str(row) for row in governed_rows + quarantine_rows)
    for raw_value in raw_pii_values:
        assert raw_value not in all_text


def test_all_good_batch_quarantines_nothing(tmp_db_path: Path, fixed_clock):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    contract = _load_commercial_loan_contract()

    raw = generate_loan_records(count=15, bad_record_rate=0.0, seed=55)
    run_id = new_pipeline_run_id()
    stamped = _stamp(raw, run_id, fixed_clock)

    gateway = ValidationGateway(con, PIIHashingService(TEST_HASH_KEY))
    result = gateway.run(stamped, contract, run_id)

    assert result.quarantined_count == 0
    assert result.governed_count == 15
    assert result.dq_pass_rate == 1.0
    con.close()


def test_governed_store_reads_back_what_the_gateway_wrote(tmp_db_path: Path, fixed_clock):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    contract = _load_commercial_loan_contract()

    raw = generate_loan_records(count=12, bad_record_rate=0.25, seed=444)
    run_id = new_pipeline_run_id()
    stamped = _stamp(raw, run_id, fixed_clock)

    gateway = ValidationGateway(con, PIIHashingService(TEST_HASH_KEY))
    result = gateway.run(stamped, contract, run_id)

    governed_records = GovernedStore(con).read_by_pipeline_run_id(run_id)
    con.close()

    assert len(governed_records) == result.governed_count
    all_loan_ids = {s.record.loan_id for s in stamped}
    assert {r.loan_id for r in governed_records}.issubset(all_loan_ids)
    for record in governed_records:
        assert record.pipeline_run_id == run_id
        assert record.contract_version == contract.version
        # governed records are exactly the ones a direct re-check confirms valid
        assert record.outstanding_balance >= 0
        assert 1 <= record.internal_credit_risk_grade <= 10
        assert record.asset_class in {"CRE", "C&I"}
