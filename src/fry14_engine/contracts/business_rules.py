"""Business rule predicates, keyed by `rule_id`. Each predicate takes the
record as a plain dict (python-typed values, e.g. from
`RawLoanRecord.model_dump()`) and returns True if the record *complies*
with the rule, False if it violates it. A predicate that can't evaluate a
rule because a required field is missing returns True (not this rule's
concern — a missing field is caught by that field's own `nullable` check).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

PredicateFn = Callable[[dict[str, Any]], bool]


def maturity_after_origination(record: dict[str, Any]) -> bool:
    origination = record.get("origination_date")
    maturity = record.get("maturity_date")
    if origination is None or maturity is None:
        return True
    return maturity >= origination


BUSINESS_RULE_REGISTRY: dict[str, PredicateFn] = {
    "MATURITY_BEFORE_ORIGINATION": maturity_after_origination,
}
