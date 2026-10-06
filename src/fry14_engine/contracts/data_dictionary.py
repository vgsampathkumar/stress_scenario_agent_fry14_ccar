"""Data dictionary generator: renders a human-readable field reference
directly from a `DataContract` document, so the dictionary can never drift
from the contract that's actually enforced — there is no second,
hand-maintained copy to go stale. Part of the Phase 7 documentation pass
(03-implementation-plan.md Phase 7, "data dictionary generated from
contract definitions").
"""

from __future__ import annotations

from fry14_engine.contracts.models import DataContract, FieldContract


def _field_constraint_summary(field: FieldContract) -> str:
    parts: list[str] = []
    if field.allowed_range is not None:
        lo = field.allowed_range.min
        hi = field.allowed_range.max
        if lo is not None and hi is not None:
            parts.append(f"{lo}-{hi}")
        elif lo is not None:
            parts.append(f">= {lo}")
        elif hi is not None:
            parts.append(f"<= {hi}")
    if field.allowed_values is not None:
        parts.append(", ".join(field.allowed_values))
    return "; ".join(parts) if parts else "-"


def generate_data_dictionary(contract: DataContract) -> str:
    """Render `contract` as a Markdown document: one table row per field,
    plus a section listing business rules. PII fields are flagged in their
    own column — a reader never has to cross-reference the contract source
    to know which fields carry PII."""
    lines: list[str] = []
    w = lines.append

    w(f"# Data Dictionary: {contract.contract_id} v{contract.version}")
    w("")
    w(f"Effective date: {contract.effective_date}")
    w("")
    w("| Field | Type | Nullable | PII | Constraint | Reason code(s) |")
    w("|---|---|---|---|---|---|")
    for field in contract.fields:
        applicable_codes: list[str] = []
        if not field.nullable:
            applicable_codes.append(field.null_reason_code)
        if field.allowed_range is not None or field.allowed_values is not None:
            applicable_codes.append(field.constraint_reason_code)
        reason_codes = ", ".join(applicable_codes) if applicable_codes else "-"
        w(
            f"| {field.field_name} | {field.data_type} | {field.nullable} | "
            f"{'yes' if field.pii else ''} | {_field_constraint_summary(field)} | {reason_codes} |"
        )
    w("")

    if contract.business_rules:
        w("## Business rules")
        w("")
        for rule in contract.business_rules:
            w(f"- **{rule.rule_id}** ({rule.severity}): {rule.description}")
        w("")

    return "\n".join(lines)
