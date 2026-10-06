"""Stress Engine (C28) formulas: pure, unit-testable functions implementing
the per-loan, per-quarter stress calculation. See 02-design-document.md
§3.18.

```
Δx(v,q)   = scenario(v,q) - scenario(v,0) + adhoc_shock(v,q)   // jump-off relative
S_PD(i,q) = Σ_v beta(seg_i, PD, v) x Δx(v,q)
m_PD      = clamp(1 + grade_sensitivity(grade_i) x S_PD, floor, cap)
m_LGD     = clamp(1 + Σ_v beta(seg_i, LGD, v) x Δx(v,q), floor, cap)
d         = clamp(Σ_v beta(seg_i, DRAWDOWN, v) x Δx(v,q), 0, 1 - CCF_i)

pd_s      = min(1, PD_i' x m_PD)        // PD_i' = grid PD after grade migration, else PD_i
lgd_s     = min(1, LGD_i x m_LGD)
ccf_s     = CCF_i + d
EAD_s     = outstanding_balance_i + unadvanced_commitment_i x ccf_s
EL_s      = pd_s x lgd_s x EAD_s
RWA_s     = EAD_s x RiskWeight(asset_class_i)                   // standardized: no PD term
```

Static balance sheet: `outstanding_balance`/`unadvanced_commitment` are held
at the jump-off (quarter-0) position for every projection quarter — this
module never re-derives a balance from a prior quarter's stressed state.

Metric sensitivity is by construction here, not by convention: `RWA_s`
depends only on `EAD_s` and the (unstressed) risk weight — a PD or LGD
shock literally cannot reach it, satisfying requirement AG-3.5.
"""

from __future__ import annotations

from decimal import Decimal

from fry14_engine.scenario.models import MacroVariable, ScenarioName, ShockTransform
from fry14_engine.scenario.spec_models import AdhocShock, AdhocShockType


def _clamp(value: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    return max(lo, min(hi, value))


def _normalize_adhoc_for_transform(shock: AdhocShock, transform: ShockTransform) -> Decimal | None:
    """Convert an ad-hoc shock's magnitude into the units a given
    translation-table transform expects, or return None if the shock's
    `shock_type` doesn't semantically apply under that transform (e.g. a
    PCT_CHANGE shock has no meaning against a LEVEL_CHANGE-transform beta
    entry) — such a shock simply doesn't contribute to that Δx, rather
    than raising, since a different beta entry for the same variable may
    use the matching transform."""
    if transform == ShockTransform.LEVEL_CHANGE:
        if shock.shock_type == AdhocShockType.ADD_BPS:
            return shock.magnitude / Decimal(100)
        if shock.shock_type == AdhocShockType.ADD_PCT_POINTS:
            return shock.magnitude
        return None
    if shock.shock_type == AdhocShockType.PCT_CHANGE:
        return shock.magnitude
    return None


def compute_delta_x(
    variable: MacroVariable,
    quarter: int,
    transform: ShockTransform,
    scenario_name: ScenarioName | None,
    supervisory_values: dict[tuple[ScenarioName, int, MacroVariable], Decimal] | None,
    adhoc_shocks: list[AdhocShock],
) -> Decimal:
    """Jump-off-relative change in `variable` by `quarter`, in the units
    `transform` expects. `supervisory_values`/`scenario_name` may be None
    (no supervisory scenario selected — e.g. a pure ad-hoc, EXPLORATORY
    request), in which case only ad-hoc shocks contribute."""
    base_delta = Decimal(0)
    if scenario_name is not None and supervisory_values is not None:
        v0 = supervisory_values[(scenario_name, 0, variable)]
        vq = supervisory_values[(scenario_name, quarter, variable)]
        if transform == ShockTransform.LEVEL_CHANGE:
            base_delta = vq - v0
        elif v0 != 0:
            base_delta = (vq - v0) / v0

    adhoc_delta = Decimal(0)
    for shock in adhoc_shocks:
        if shock.variable != variable or quarter not in shock.quarters:
            continue
        normalized = _normalize_adhoc_for_transform(shock, transform)
        if normalized is not None:
            adhoc_delta += normalized

    return base_delta + adhoc_delta


def compute_pd_multiplier(
    s_pd: Decimal, grade_scaling: Decimal, floor: Decimal, cap: Decimal
) -> Decimal:
    return _clamp(Decimal(1) + grade_scaling * s_pd, floor, cap)


def compute_lgd_multiplier(s_lgd: Decimal, floor: Decimal, cap: Decimal) -> Decimal:
    return _clamp(Decimal(1) + s_lgd, floor, cap)


def compute_drawdown_uplift(s_drawdown: Decimal, base_ccf: Decimal) -> Decimal:
    return _clamp(s_drawdown, Decimal(0), Decimal(1) - base_ccf)


def compute_stressed_pd(effective_pd: Decimal, pd_multiplier: Decimal) -> Decimal:
    return min(Decimal(1), effective_pd * pd_multiplier)


def compute_stressed_lgd(lgd: Decimal, lgd_multiplier: Decimal) -> Decimal:
    return min(Decimal(1), lgd * lgd_multiplier)


def compute_stressed_ccf(base_ccf: Decimal, drawdown_uplift: Decimal) -> Decimal:
    return base_ccf + drawdown_uplift


def compute_stressed_ead(
    outstanding_balance: Decimal, unadvanced_commitment: Decimal, stressed_ccf: Decimal
) -> Decimal:
    return outstanding_balance + unadvanced_commitment * stressed_ccf


def compute_stressed_el(
    pd_stressed: Decimal, lgd_stressed: Decimal, ead_stressed: Decimal
) -> Decimal:
    return pd_stressed * lgd_stressed * ead_stressed


def compute_stressed_rwa(ead_stressed: Decimal, risk_weight: Decimal) -> Decimal:
    """Standardized approach: no PD term. A PD shock cannot move this by
    construction — see requirement AG-3.5."""
    return ead_stressed * risk_weight
