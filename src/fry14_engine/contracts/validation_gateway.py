"""Contract Validation + PII Governance Gateway: orchestrates one pass over
a batch of stamped (metadata-carrying) records: validate against the
active contract, hash every PII field regardless of pass/fail — before any
further branching — then route: valid records to the Governed Store,
invalid records to the Quarantine Store with reason codes. Per requirement
2.2, the valid stream is never blocked by invalid records in the same
batch: both are produced from a single per-record pass. See
02-design-document.md §4 steps 2-4.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

from fry14_engine.common.ids import ClockFn, new_record_id, utc_now
from fry14_engine.contracts.models import DataContract
from fry14_engine.contracts.validation_engine import ValidationEngine
from fry14_engine.ingestion.stamped import StampedRecord
from fry14_engine.pii.governed_models import GovernedLoanRecord
from fry14_engine.pii.governed_store import GovernedStore
from fry14_engine.pii.hashing_service import PIIHashingService
from fry14_engine.quarantine.models import QuarantineRecord
from fry14_engine.quarantine.store import QuarantineStore


@dataclass
class ValidationRunResult:
    pipeline_run_id: str
    contract_id: str
    contract_version: str
    total_count: int
    governed_count: int = 0
    quarantined_count: int = 0
    reason_code_counts: dict[str, int] = field(default_factory=dict)

    @property
    def dq_pass_rate(self) -> float:
        if self.total_count == 0:
            return 1.0
        return self.governed_count / self.total_count


class ValidationGateway:
    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        pii_hashing_service: PIIHashingService,
        clock: ClockFn = utc_now,
    ) -> None:
        self._governed_store = GovernedStore(connection)
        self._quarantine_store = QuarantineStore(connection)
        self._pii_hashing_service = pii_hashing_service
        self._clock = clock

    def run(
        self,
        stamped_records: list[StampedRecord],
        contract: DataContract,
        pipeline_run_id: str,
    ) -> ValidationRunResult:
        engine = ValidationEngine(contract)
        pii_fields = {f.field_name for f in contract.fields if f.pii}

        governed_rows: list[GovernedLoanRecord] = []
        quarantine_rows: list[QuarantineRecord] = []
        reason_code_counts: dict[str, int] = {}

        for stamped in stamped_records:
            record = stamped.record
            outcome = engine.validate(record)

            # PII is hashed regardless of pass/fail, before either branch
            # persists anything — so quarantine never stores raw PII either.
            hashed_data = self._pii_hashing_service.hash_record_fields(
                record.model_dump(mode="json"), pii_fields
            )

            if outcome.is_valid:
                governed_rows.append(
                    GovernedLoanRecord(
                        governed_id=new_record_id(),
                        loan_id=record.loan_id,
                        borrower_key_hash=hashed_data.get("borrower_tax_id"),
                        borrower_name_hash=hashed_data.get("borrower_legal_name"),
                        borrower_address_hash=hashed_data.get("borrower_address"),
                        counterparty_id=record.counterparty_id,
                        asset_class=record.asset_class,
                        internal_credit_risk_grade=record.internal_credit_risk_grade,
                        credit_score=record.credit_score,
                        outstanding_balance=record.outstanding_balance,
                        unadvanced_commitment=record.unadvanced_commitment,
                        maturity_date=record.maturity_date,
                        probability_of_default=record.probability_of_default,
                        loss_given_default=record.loss_given_default,
                        portfolio_segment=record.portfolio_segment,
                        pipeline_run_id=pipeline_run_id,
                        contract_version=contract.version,
                        ingestion_timestamp=stamped.metadata.ingestion_timestamp,
                    )
                )
                continue

            for code in outcome.reason_codes:
                reason_code_counts[code] = reason_code_counts.get(code, 0) + 1

            quarantine_rows.append(
                QuarantineRecord(
                    quarantine_id=new_record_id(),
                    loan_id=record.loan_id,
                    pipeline_run_id=pipeline_run_id,
                    contract_id=contract.contract_id,
                    contract_version=contract.version,
                    original_record=hashed_data,
                    exception_reason_codes=outcome.reason_codes,
                    rejected_at=self._clock(),
                )
            )

        self._governed_store.write(governed_rows)
        self._quarantine_store.write(quarantine_rows)

        return ValidationRunResult(
            pipeline_run_id=pipeline_run_id,
            contract_id=contract.contract_id,
            contract_version=contract.version,
            total_count=len(stamped_records),
            governed_count=len(governed_rows),
            quarantined_count=len(quarantine_rows),
            reason_code_counts=reason_code_counts,
        )
