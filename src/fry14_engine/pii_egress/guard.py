"""PII Egress Guard (C31): inspects every payload before it would be sent
to an LLM endpoint, blocking the call (not redacting and continuing) if
PII leaked past hashing. See 02-design-document.md §3.21.

**Scope note:** implements the pattern-detector half of §3.21's
description (SSN/EIN-shaped strings) — fail-closed, recursive over any
JSON-like structure. The "name/address heuristics on unexpected fields"
half needs the calling contract's own PII field list to know which fields
are "unexpected" in the first place; this guard has no contract awareness
by design (it must work on arbitrary agent-bound payloads, not just
contract-shaped records), so that half is deferred rather than faked with
a heuristic that would mostly just flag legitimate free-text fields.
"""

from __future__ import annotations

import re
from typing import Any

_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_EIN_PATTERN = re.compile(r"\b\d{2}-\d{7}\b")

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SSN_FORMAT", _SSN_PATTERN),
    ("EIN_FORMAT", _EIN_PATTERN),
]


class PiiEgressBlockedError(Exception):
    def __init__(self, field_path: str, pattern_name: str) -> None:
        super().__init__(f"PII_EGRESS_BLOCKED: field {field_path!r} matched {pattern_name}")
        self.field_path = field_path
        self.pattern_name = pattern_name


class PiiEgressGuard:
    def scan_text(self, text: str, field_path: str = "<text>") -> None:
        for pattern_name, pattern in _PATTERNS:
            if pattern.search(text):
                raise PiiEgressBlockedError(field_path, pattern_name)

    def scan_payload(self, payload: Any) -> None:
        """Recursively scans a JSON-like structure (nested dict/list of
        str/int/float/bool/None) for leaked PII. Raises on the first
        match — fail-closed, not best-effort redaction."""
        self._scan(payload, "$")

    def _scan(self, value: Any, path: str) -> None:
        if isinstance(value, str):
            self.scan_text(value, path)
        elif isinstance(value, dict):
            for key, nested in value.items():
                self._scan(nested, f"{path}.{key}")
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                self._scan(nested, f"{path}[{index}]")
