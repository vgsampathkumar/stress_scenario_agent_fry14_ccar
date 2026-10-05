"""Event-driven ingestion adapter: simulates a message-queue/topic consumer
for near-real-time loan record updates via a pluggable `EventSource`.

Per 01-approach-paper.md §8 (assumptions), a full enterprise streaming
platform is out of scope for this phase — a file-append-log or in-memory
queue is sufficient to demonstrate the event-driven ingestion path while
keeping `EventStreamAdapter` itself agnostic to the underlying transport.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from fry14_engine.common.enums import IngestionChannel
from fry14_engine.ingestion.adapter import IngestionAdapter, IngestionBatch


class EventSource(Protocol):
    def poll(self) -> list[dict[str, Any]]:
        """Return all messages available since the last poll() call."""
        ...


class InMemoryEventSource:
    """Test/demo event source: messages are pushed via `publish()` and
    consumed (once each, in order) via `poll()`."""

    def __init__(self) -> None:
        self._queue: list[dict[str, Any]] = []

    def publish(self, message: dict[str, Any]) -> None:
        self._queue.append(message)

    def poll(self) -> list[dict[str, Any]]:
        messages, self._queue = self._queue, []
        return messages


class FileAppendLogEventSource:
    """Reads newly-appended JSON-Lines messages from a file since the last
    poll(), tracking a byte offset — a minimal stand-in for a real broker's
    consumer-offset semantics, without requiring an actual broker."""

    def __init__(self, file_path: Path | str) -> None:
        self.file_path = Path(file_path)
        self._offset = 0

    def poll(self) -> list[dict[str, Any]]:
        if not self.file_path.exists():
            return []
        with self.file_path.open(encoding="utf-8") as fh:
            fh.seek(self._offset)
            new_lines = fh.readlines()
            self._offset = fh.tell()
        return [json.loads(line) for line in new_lines if line.strip()]


class EventStreamAdapter(IngestionAdapter):
    channel = IngestionChannel.EVENT

    def __init__(self, event_source: EventSource, source_system_of_record: str) -> None:
        self.event_source = event_source
        self.source_system_of_record = source_system_of_record

    def read(self) -> IngestionBatch:
        batch = IngestionBatch()
        for payload in self.event_source.poll():
            self._normalize_into(payload, batch)
        return batch
