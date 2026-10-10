"""Synthetic commercial loan record generator.

Produces source-shaped (pre-ingestion) dicts, optionally injecting specific,
labeled "bad" records so the contract-validation/quarantine path (Phase 2)
has deterministic, reproducible fixtures to validate against. See
03-implementation-plan.md Phase 1 and 02-design-document.md §6 (exception
reason code catalog).
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from faker import Faker

ASSET_CLASSES = ["CRE", "C&I"]
PORTFOLIO_SEGMENTS = ["MIDDLE_MARKET", "LARGE_CORPORATE", "SMALL_BUSINESS"]


@dataclass(frozen=True)
class BadRecordSpec:
    """A labeled way a synthetic record can be deliberately broken — the
    name matches an exception reason code in 02-design-document.md §6."""

    name: str
    apply: Callable[[dict, random.Random], dict]


def _negative_balance(record: dict, rng: random.Random) -> dict:  # noqa: ARG001
    record["outstanding_balance"] = -abs(record["outstanding_balance"])
    return record


def _missing_credit_score(record: dict, rng: random.Random) -> dict:  # noqa: ARG001
    record["credit_score"] = None
    return record


def _invalid_credit_grade(record: dict, rng: random.Random) -> dict:
    # Uses the run's seeded `rng`, not the global `random` module — otherwise
    # reproducibility breaks across repeated generate_loan_records() calls in
    # the same process (global random state carries over between calls).
    record["internal_credit_risk_grade"] = rng.choice([0, 11, 99])
    return record


def _null_mandatory_field(record: dict, rng: random.Random) -> dict:  # noqa: ARG001
    record["asset_class"] = None
    return record


BAD_RECORD_SPECS: list[BadRecordSpec] = [
    BadRecordSpec("NEGATIVE_BALANCE", _negative_balance),
    BadRecordSpec("MISSING_CREDIT_SCORE", _missing_credit_score),
    BadRecordSpec("INVALID_CREDIT_GRADE", _invalid_credit_grade),
    BadRecordSpec("NULL_MANDATORY_FIELD", _null_mandatory_field),
]


def _one_good_record(fake: Faker, rng: random.Random, index: int) -> dict:
    origination = fake.date_between(start_date="-5y", end_date="-30d")
    maturity = origination + timedelta(days=rng.choice([365, 1095, 1825, 3650]))
    return {
        "loan_id": f"LN-{index:08d}",
        "borrower_tax_id": fake.ssn(),
        "borrower_legal_name": fake.company(),
        "borrower_address": fake.address().replace("\n", ", "),
        "counterparty_id": f"CP-{rng.randint(10000, 99999)}",
        "asset_class": rng.choice(ASSET_CLASSES),
        "internal_credit_risk_grade": rng.randint(1, 10),
        "credit_score": rng.randint(580, 820),
        "outstanding_balance": round(rng.uniform(50_000, 25_000_000), 2),
        "unadvanced_commitment": round(rng.uniform(0, 5_000_000), 2),
        "origination_date": origination.isoformat(),
        "maturity_date": maturity.isoformat(),
        "probability_of_default": round(rng.uniform(0.001, 0.15), 6),
        "loss_given_default": round(rng.uniform(0.1, 0.65), 6),
        "portfolio_segment": rng.choice(PORTFOLIO_SEGMENTS),
    }


def generate_loan_records(
    count: int,
    bad_record_rate: float = 0.0,
    seed: int | None = None,
    start_index: int = 0,
) -> list[dict]:
    """Generate `count` synthetic commercial loan records.

    If `bad_record_rate` > 0, that fraction of records is deliberately
    broken via one of `BAD_RECORD_SPECS` (cycled deterministically), e.g.
    for exercising Phase 2 quarantine logic. With a fixed `seed`, output is
    fully reproducible.

    `loan_id`s are numbered from `start_index`. Pass a non-overlapping
    `start_index` when generating multiple batches that will be processed
    together in the same run (e.g. a batch channel and an event channel) —
    otherwise two calls both numbering from 0 collide on `loan_id`
    downstream wherever it's part of a uniqueness constraint (e.g.
    `metrics.loan_risk_metrics`'s primary key).
    """
    if not 0.0 <= bad_record_rate <= 1.0:
        raise ValueError("bad_record_rate must be between 0.0 and 1.0")

    rng = random.Random(seed)
    fake = Faker()
    fake.seed_instance(seed)

    bad_interval = round(1 / bad_record_rate) if bad_record_rate > 0 else 0

    records: list[dict] = []
    for offset in range(count):
        index = start_index + offset
        record = _one_good_record(fake, rng, index)
        if bad_interval and offset % bad_interval == 0:
            spec = BAD_RECORD_SPECS[(offset // bad_interval) % len(BAD_RECORD_SPECS)]
            record = spec.apply(record, rng)
        records.append(record)
    return records


def generate_schema_change_drops_credit_score_batch(
    count: int, source_system_of_record: str, seed: int | None = None, start_index: int = 0
) -> list[dict]:
    """A labeled root-cause fixture for AG-2 (Phase 10): simulates one
    source feed's schema change dropping `credit_score` entirely — every
    record in this batch shares the same `source_system_of_record` and is
    missing `credit_score`, so a correct triage attributes 100% of the
    `MISSING_CREDIT_SCORE` cluster to that one source system. Unlike
    `BAD_RECORD_SPECS.MISSING_CREDIT_SCORE` (cycled uniformly across a
    mixed batch), this ties the defect to a specific, attributable
    dimension so root-cause identification has a deterministic ground
    truth to check against."""
    rng = random.Random(seed)
    fake = Faker()
    fake.seed_instance(seed)
    records = []
    for offset in range(count):
        record = _one_good_record(fake, rng, start_index + offset)
        record["source_system_of_record"] = source_system_of_record
        record["credit_score"] = None
        records.append(record)
    return records


def generate_negative_balance_entity_batch(
    count: int, counterparty_id: str, seed: int | None = None, start_index: int = 0
) -> list[dict]:
    """A labeled root-cause fixture for AG-2 (Phase 10): simulates one
    counterparty's feed sending negative balances — every record in this
    batch shares the same `counterparty_id` and has a negated
    `outstanding_balance`, so a correct triage attributes 100% of the
    `NEGATIVE_BALANCE` cluster to that one counterparty."""
    rng = random.Random(seed)
    fake = Faker()
    fake.seed_instance(seed)
    records = []
    for offset in range(count):
        record = _one_good_record(fake, rng, start_index + offset)
        record["counterparty_id"] = counterparty_id
        record["outstanding_balance"] = -abs(record["outstanding_balance"])
        records.append(record)
    return records
