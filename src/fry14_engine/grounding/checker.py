"""Numeric Grounding Checker (C29): resolves `{{token}}` bindings in a
narrative template against stored tool outputs, renders the text, and
scans for any numeric token that did **not** come from a binding — an
injected "free" number. Either failure mode sets `grounding_status =
FAILED` and blocks release. See 02-design-document.md §3.19.

Deliberately plain code, no LLM: AG-4 drafts `template_text` with an LLM,
but every number that actually reaches a reader is substituted here from
real data, and this scan is what catches an LLM that typed a raw number
instead of a binding.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from fry14_engine.grounding.models import GroundingResult, GroundingStatus

_BINDING_PATTERN = re.compile(r"\{\{([^}]+)\}\}")

# Numeric-looking substrings allowed to appear in the template's own
# literal text (never inside a binding) without being treated as an
# unbound figure — dates, quarter labels, and regulation names, per
# design doc §3.19's own allowlist description.
_ALLOWLIST_PATTERNS = [
    re.compile(r"\bQ[1-9]\b"),  # quarter labels: Q1..Q9
    re.compile(r"\b20\d{2}-(0[1-9]|1[0-2])\b"),  # reporting periods: YYYY-MM
    re.compile(r"\b20\d{2}\b"),  # bare years
    re.compile(r"FR Y-14"),  # regulation name
    re.compile(r"\bCCAR\b"),
]

_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")


def _scan_for_unbound_numbers(template_text: str) -> list[str]:
    literal_text = _BINDING_PATTERN.sub("", template_text)
    for pattern in _ALLOWLIST_PATTERNS:
        literal_text = pattern.sub("", literal_text)
    return _NUMBER_PATTERN.findall(literal_text)


class GroundingChecker:
    def check(self, template_text: str, resolver: Callable[[str], str | None]) -> GroundingResult:
        """`resolver(token)` returns the formatted value for a binding
        token (the text between `{{` and `}}`, e.g. `run:7f3a.delta_EL`),
        or `None` if it can't be resolved — an unresolved binding fails
        grounding exactly like an unbound number does."""
        unbound_numbers = _scan_for_unbound_numbers(template_text)
        unresolved_tokens: list[str] = []

        def _substitute(match: re.Match[str]) -> str:
            token = match.group(1)
            value = resolver(token)
            if value is None:
                unresolved_tokens.append(token)
                return match.group(0)
            return value

        rendered_text = _BINDING_PATTERN.sub(_substitute, template_text)
        status = (
            GroundingStatus.PASSED
            if not unresolved_tokens and not unbound_numbers
            else GroundingStatus.FAILED
        )
        return GroundingResult(
            rendered_text=rendered_text,
            status=status,
            unresolved_tokens=unresolved_tokens,
            unbound_numbers=unbound_numbers,
        )
