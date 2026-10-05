"""Batch file ingestion adapter: reads a CSV, JSON, or JSON-Lines extract
representing a synthetic commercial loan file drop. See
02-design-document.md §3.1 (Ingestion Gateway) and requirement 2.1
("Multi-Source Ingestion").
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from fry14_engine.common.enums import IngestionChannel
from fry14_engine.ingestion.adapter import IngestionAdapter, IngestionBatch


class BatchFileAdapter(IngestionAdapter):
    channel = IngestionChannel.BATCH

    def __init__(self, file_path: Path | str, source_system_of_record: str) -> None:
        self.file_path = Path(file_path)
        self.source_system_of_record = source_system_of_record

    def read(self) -> IngestionBatch:
        batch = IngestionBatch()
        for payload in self._read_rows():
            self._normalize_into(payload, batch)
        return batch

    def _read_rows(self) -> list[dict[str, Any]]:
        suffix = self.file_path.suffix.lower()
        if suffix == ".csv":
            with self.file_path.open(newline="", encoding="utf-8") as fh:
                return [self._clean_csv_row(row) for row in csv.DictReader(fh)]
        if suffix == ".jsonl":
            with self.file_path.open(encoding="utf-8") as fh:
                return [json.loads(line) for line in fh if line.strip()]
        if suffix == ".json":
            with self.file_path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else [data]
        raise ValueError(f"Unsupported batch file format: {suffix}")

    @staticmethod
    def _clean_csv_row(row: dict[str, str]) -> dict[str, Any]:
        """CSV has no native null — an empty cell means "missing", not the
        literal string "". Normalize to None so Phase 2's non-null contract
        checks (not a Phase-1 parse failure) are what catch it."""
        return {key: (value if value not in ("", None) else None) for key, value in row.items()}
