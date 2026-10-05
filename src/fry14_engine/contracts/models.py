"""Data contract document model: schema + business rules, versioned. See
02-design-document.md §2.2 and requirement 2.2 ("Contract Validation").

A note on `BusinessRule.expression`: it is documentation only, not executed.
Rule *logic* lives in `contracts.business_rules.BUSINESS_RULE_REGISTRY`, a
small, reviewed Python registry keyed by `rule_id` — the same
reference-data-driven-but-code-implements-logic pattern used elsewhere in
this project (e.g. the Risk Metric Engine's formulas vs. its reference
tables). This deliberately avoids evaluating arbitrary expressions from
config, which would be an injection risk for no real benefit at this scale.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from fry14_engine.common.enums import RuleSeverity


class FieldDataType(StrEnum):
    STRING = "STRING"
    INT = "INT"
    DECIMAL = "DECIMAL"
    DATE = "DATE"
    BOOLEAN = "BOOLEAN"


PYTHON_TYPE_BY_FIELD_DATA_TYPE: dict[FieldDataType, type] = {
    FieldDataType.STRING: str,
    FieldDataType.INT: int,
    FieldDataType.DECIMAL: Decimal,
    FieldDataType.DATE: date,
    FieldDataType.BOOLEAN: bool,
}


class AllowedRange(BaseModel):
    model_config = ConfigDict(frozen=True)

    min: Decimal | None = None
    max: Decimal | None = None


class FieldContract(BaseModel):
    """One field's contract: type, nullability, and the reason codes to
    emit on violation. `null_reason_code` fires when a non-nullable field is
    missing; `constraint_reason_code` fires on a type, range, or
    allowed-values violation. Both default to generic catalog codes
    (02-design-document.md §6) and can be overridden per field for a more
    specific code (e.g. `INVALID_CREDIT_GRADE` instead of the generic
    `TYPE_MISMATCH`)."""

    model_config = ConfigDict(frozen=True)

    field_name: str
    data_type: FieldDataType
    nullable: bool = True
    allowed_range: AllowedRange | None = None
    allowed_values: list[str] | None = None
    pii: bool = False
    null_reason_code: str = "NULL_MANDATORY_FIELD"
    constraint_reason_code: str = "TYPE_MISMATCH"


class BusinessRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str
    description: str
    expression: str
    severity: RuleSeverity = RuleSeverity.REJECT


class DataContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract_id: str
    version: str
    effective_date: date
    fields: list[FieldContract]
    business_rules: list[BusinessRule] = []
