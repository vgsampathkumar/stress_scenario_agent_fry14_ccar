"""`get_quarantine_summary`: the deterministic clustering tool AG-2 reasons
over — never raw records. Groups open quarantine records by reason code x
source system x rejection-day window, with per-field null-rate stats and
up to 20 capped (already-hashed) sample records per cluster. See
02-design-document.md §3.17 and requirements.md §3.3.

**Scope note:** the design doc's clustering dimensions include "source
entity", but `quarantine.quarantine_record` has never captured
`source_entity_code` — that metadata lives on the landing-zone record, not
the quarantine one (see schemas/003_quarantine.sql). This implementation
clusters by (reason_code, source_system_of_record, rejection day) instead,
and approximates "ingestion window" with `rejected_at`'s date since
`ingestion_timestamp` likewise isn't persisted on the quarantine row.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from fry14_engine.quarantine.models import QuarantineRecord

MAX_SAMPLES_PER_CLUSTER = 20

_ClusterKey = tuple[str, str | None, str]  # (reason_code, source_system_of_record, rejection_date)


@dataclass(frozen=True)
class QuarantineCluster:
    reason_code: str
    source_system_of_record: str | None
    rejection_date: str  # ISO date
    record_count: int
    null_field_rates: dict[str, float]
    sample_quarantine_ids: list[str]


@dataclass(frozen=True)
class QuarantineSummary:
    total_open_records: int
    clusters: list[QuarantineCluster]


def build_quarantine_summary(records: list[QuarantineRecord]) -> QuarantineSummary:
    groups: dict[_ClusterKey, list[QuarantineRecord]] = defaultdict(list)
    for record in records:
        source_system = record.original_record.get("source_system_of_record")
        rejection_date = record.rejected_at.date().isoformat()
        for reason_code in record.exception_reason_codes:
            groups[(reason_code, source_system, rejection_date)].append(record)

    sorted_keys = sorted(groups, key=lambda key: (key[0], key[1] or "", key[2]))
    clusters = [
        QuarantineCluster(
            reason_code=key[0],
            source_system_of_record=key[1],
            rejection_date=key[2],
            record_count=len(groups[key]),
            null_field_rates=_null_field_rates(groups[key]),
            sample_quarantine_ids=[r.quarantine_id for r in groups[key][:MAX_SAMPLES_PER_CLUSTER]],
        )
        for key in sorted_keys
    ]
    return QuarantineSummary(total_open_records=len(records), clusters=clusters)


def _null_field_rates(records: list[QuarantineRecord]) -> dict[str, float]:
    if not records:
        return {}
    field_names = {name for record in records for name in record.original_record}
    return {
        name: round(
            sum(1 for r in records if r.original_record.get(name) is None) / len(records), 4
        )
        for name in field_names
    }
