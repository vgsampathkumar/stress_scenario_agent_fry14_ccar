from __future__ import annotations

import json
from pathlib import Path

from fry14_engine.ingestion.batch_file_adapter import BatchFileAdapter
from fry14_engine.synthetic.generator import generate_loan_records
from fry14_engine.synthetic.writers import write_csv, write_jsonl


def test_reads_csv_and_normalizes_all_rows(tmp_path: Path):
    records = generate_loan_records(count=20, bad_record_rate=0.25, seed=42)
    file_path = tmp_path / "loans.csv"
    write_csv(records, file_path)

    adapter = BatchFileAdapter(file_path, source_system_of_record="CORE_LOAN_SYSTEM")
    batch = adapter.read()

    assert len(batch.records) == 20
    assert batch.parse_errors == []
    assert all(r.source_system_of_record == "CORE_LOAN_SYSTEM" for r in batch.records)


def test_csv_empty_cells_become_none_not_parse_errors(tmp_path: Path):
    records = generate_loan_records(count=5, bad_record_rate=1.0, seed=1)  # all NEGATIVE_BALANCE
    # Force a null-mandatory-field case explicitly via raw dict manipulation.
    records[0]["asset_class"] = None
    file_path = tmp_path / "loans.csv"
    write_csv(records, file_path)

    adapter = BatchFileAdapter(file_path, source_system_of_record="CORE_LOAN_SYSTEM")
    batch = adapter.read()

    assert len(batch.records) == 5
    assert batch.records[0].asset_class is None


def test_reads_jsonl(tmp_path: Path):
    records = generate_loan_records(count=10, seed=7)
    file_path = tmp_path / "loans.jsonl"
    write_jsonl(records, file_path)

    adapter = BatchFileAdapter(file_path, source_system_of_record="EVENT_FEED")
    batch = adapter.read()

    assert len(batch.records) == 10
    assert batch.parse_errors == []


def test_reads_json_array(tmp_path: Path):
    records = generate_loan_records(count=3, seed=3)
    file_path = tmp_path / "loans.json"
    file_path.write_text(json.dumps(records), encoding="utf-8")

    adapter = BatchFileAdapter(file_path, source_system_of_record="CORE_LOAN_SYSTEM")
    batch = adapter.read()

    assert len(batch.records) == 3


def test_malformed_row_becomes_parse_error_not_a_crash(tmp_path: Path):
    good = generate_loan_records(count=2, seed=9)
    file_path = tmp_path / "loans.jsonl"
    lines = [json.dumps(r) for r in good]
    lines.append(json.dumps({"loan_id": "LN-BAD", "internal_credit_risk_grade": "not-a-number"}))
    file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    adapter = BatchFileAdapter(file_path, source_system_of_record="CORE_LOAN_SYSTEM")
    batch = adapter.read()

    assert len(batch.records) == 2
    assert len(batch.parse_errors) == 1
    assert batch.parse_errors[0].raw_payload["loan_id"] == "LN-BAD"


def test_unsupported_extension_raises():
    import pytest

    adapter = BatchFileAdapter(Path("loans.parquet"), source_system_of_record="X")
    with pytest.raises(ValueError, match="Unsupported batch file format"):
        adapter.read()
