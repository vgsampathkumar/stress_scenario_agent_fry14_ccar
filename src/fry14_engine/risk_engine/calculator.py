"""Risk Metric Engine (C10) formulas: pure, unit-testable functions. See
02-design-document.md §3.5 and requirement 2.4.

Note the formulas take no `credit_rating_grade` input — under the
standardized approach, RWA moves through EAD (balance/drawdown changes),
not through PD, and EL moves through PD/LGD/EAD. Grade is an output
dimension (for aggregation), never an input to these formulas. This
matters again in Phase 8: stress scenarios must change EL via PD/LGD
shocks and RWA only via drawdown/CCF shocks, never RWA via a PD shock —
these functions already enforce that by construction.
"""

from __future__ import annotations

from decimal import Decimal


def calculate_ead(
    outstanding_balance: Decimal, unadvanced_commitment: Decimal, ccf: Decimal
) -> Decimal:
    """EAD = outstanding balance + unadvanced commitment x credit conversion factor."""
    return outstanding_balance + unadvanced_commitment * ccf


def calculate_el(
    probability_of_default: Decimal, loss_given_default: Decimal, ead: Decimal
) -> Decimal:
    """EL = PD x LGD x EAD."""
    return probability_of_default * loss_given_default * ead


def calculate_rwa(ead: Decimal, risk_weight: Decimal) -> Decimal:
    """RWA = EAD x regulatory risk weight for the asset class."""
    return ead * risk_weight
