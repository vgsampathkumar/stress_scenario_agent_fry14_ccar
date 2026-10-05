"""Validation Engine (C5): evaluates a record against a `DataContract` and
returns *every* applicable exception reason code, not just the first one —
a record can fail multiple checks simultaneously. See 02-design-document.md
§3.2 and requirement 2.2 ("Contract Validation").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fry14_engine.contracts.business_rules import BUSINESS_RULE_REGISTRY
from fry14_engine.contracts.models import (
    PYTHON_TYPE_BY_FIELD_DATA_TYPE,
    DataContract,
    FieldContract,
)
from fry14_engine.ingestion.models import RawLoanRecord


@dataclass(frozen=True)
class ValidationOutcome:
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        return len(self.reason_codes) == 0


class ValidationEngine:
    def __init__(self, contract: DataContract) -> None:
        self._contract = contract

    def validate(self, record: RawLoanRecord) -> ValidationOutcome:
        data = record.model_dump()
        reason_codes: list[str] = []

        for field_contract in self._contract.fields:
            reason_codes.extend(self._check_field(field_contract, data))

        for rule in self._contract.business_rules:
            predicate = BUSINESS_RULE_REGISTRY[rule.rule_id]
            if not predicate(data):
                reason_codes.append(rule.rule_id)

        return ValidationOutcome(reason_codes=tuple(reason_codes))

    @staticmethod
    def _check_field(field_contract: FieldContract, data: dict[str, Any]) -> list[str]:
        value = data.get(field_contract.field_name)
        codes: list[str] = []

        if value is None:
            if not field_contract.nullable:
                codes.append(field_contract.null_reason_code)
            return codes

        expected_type = PYTHON_TYPE_BY_FIELD_DATA_TYPE[field_contract.data_type]
        if not isinstance(value, expected_type):
            codes.append(field_contract.constraint_reason_code)
            return codes

        if field_contract.allowed_range is not None:
            lo, hi = field_contract.allowed_range.min, field_contract.allowed_range.max
            if (lo is not None and value < lo) or (hi is not None and value > hi):
                codes.append(field_contract.constraint_reason_code)

        if field_contract.allowed_values is not None and value not in field_contract.allowed_values:
            codes.append(field_contract.constraint_reason_code)

        return codes
