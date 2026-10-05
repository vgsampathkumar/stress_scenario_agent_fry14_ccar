from __future__ import annotations

import json
from pathlib import Path

from fry14_engine.ingestion.event_stream_adapter import (
    EventStreamAdapter,
    FileAppendLogEventSource,
    InMemoryEventSource,
)
from fry14_engine.synthetic.generator import generate_loan_records


def test_in_memory_event_source_consumes_once():
    source = InMemoryEventSource()
    source.publish({"loan_id": "LN-1"})
    source.publish({"loan_id": "LN-2"})

    first_poll = source.poll()
    second_poll = source.poll()

    assert len(first_poll) == 2
    assert second_poll == []


def test_event_stream_adapter_normalizes_published_messages():
    source = InMemoryEventSource()
    for record in generate_loan_records(count=5, seed=11):
        source.publish(record)

    adapter = EventStreamAdapter(source, source_system_of_record="CREDIT_PERFORMANCE_FEED")
    batch = adapter.read()

    assert len(batch.records) == 5
    assert all(r.source_system_of_record == "CREDIT_PERFORMANCE_FEED" for r in batch.records)


def test_file_append_log_only_returns_new_messages_since_last_poll(tmp_path: Path):
    log_path = tmp_path / "events.jsonl"
    source = FileAppendLogEventSource(log_path)

    with log_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"loan_id": "LN-1"}) + "\n")

    first_poll = source.poll()
    assert len(first_poll) == 1

    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"loan_id": "LN-2"}) + "\n")

    second_poll = source.poll()
    assert len(second_poll) == 1
    assert second_poll[0]["loan_id"] == "LN-2"


def test_file_append_log_returns_empty_when_file_missing(tmp_path: Path):
    source = FileAppendLogEventSource(tmp_path / "does_not_exist.jsonl")
    assert source.poll() == []
