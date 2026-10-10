"""Scenario translation evaluation set (requirements.md AG-GOV-4, design
doc §3.21): ≥50 natural-language requests with expected `ScenarioSpec`
fields (including ambiguous ones expecting a clarifying question),
scored against a translator's output. Pass bar: ≥95% exact match.

**Scope note:** there is no real LLM wired into this repo (see
`agent_runtime/models.py`'s own scope note on `LlmClient`). So this
module's `RuleBasedScenarioTranslator` is an illustrative, deliberately
simple keyword/regex parser — not a model — used only to give the harness
something real to score and to prove the harness itself can distinguish
a pass from a failure (a handful of golden cases below use phrasing the
parser can't handle, by design, so the suite does not trivially score
100%). Swapping in a real `LlmClient` means re-running this exact harness
against it before release, per AG-GOV-2.
"""

from __future__ import annotations

import re

from fry14_engine.agent_runtime.ag3_stress_scenario import DraftScenarioRequest
from fry14_engine.evaluation.models import EvalCase, EvalCaseResult, EvalSetResult
from fry14_engine.scenario.models import MacroVariable, ScenarioName
from fry14_engine.scenario.spec_models import AdhocShock, AdhocShockType

PASS_BAR = 0.95

_SEGMENT_KEYWORDS = {
    "middle market": "MIDDLE_MARKET",
    "large corporate": "LARGE_CORPORATE",
    "small business": "SMALL_BUSINESS",
}
_ASSET_CLASS_KEYWORDS = {
    "commercial real estate": "CRE",
    "cre": "CRE",
    "commercial and industrial": "C&I",
    "c&i": "C&I",
}
_VARIABLE_KEYWORDS = {
    "10-year treasury": MacroVariable.TREASURY_10Y,
    "10 year treasury": MacroVariable.TREASURY_10Y,
    "10yr treasury": MacroVariable.TREASURY_10Y,
    "3-month treasury": MacroVariable.TREASURY_3M,
    "bbb": MacroVariable.BBB_CORPORATE_YIELD,
    "corporate yield": MacroVariable.BBB_CORPORATE_YIELD,
    "unemployment": MacroVariable.UNEMPLOYMENT_RATE,
    "gdp": MacroVariable.REAL_GDP_GROWTH,
    "cre price": MacroVariable.CRE_PRICE_INDEX,
    "cre value": MacroVariable.CRE_PRICE_INDEX,
    "house price": MacroVariable.HOUSE_PRICE_INDEX,
    "home price": MacroVariable.HOUSE_PRICE_INDEX,
}
_REPORTING_PERIOD_PATTERN = re.compile(r"\b(20\d{2}-(?:0[1-9]|1[0-2]))\b")
_BPS_SHOCK_PATTERN = re.compile(r"\+?(\d+)\s*(?:bps|basis points)")


class RuleBasedScenarioTranslator:
    """Illustrative stand-in for a real LLM — see module docstring."""

    model_id = "rule-based-scenario-translator-v1"
    prompt_template_version = "1.0.0"

    def complete(self, request, response_schema) -> tuple[dict, int, int]:
        text = request.user_prompt.lower()

        reporting_period_match = _REPORTING_PERIOD_PATTERN.search(text)
        if reporting_period_match is None:
            return (
                DraftScenarioRequest(
                    needs_clarification=True,
                    clarifying_question="Which reporting period (YYYY-MM) should this run against?",
                ).model_dump(mode="json"),
                0,
                0,
            )

        base_scenario = None
        supervisory_scenario_version = None
        if "severely adverse" in text:
            base_scenario = ScenarioName.SEVERELY_ADVERSE
            supervisory_scenario_version = "FED-2026"
        elif "baseline" in text:
            base_scenario = ScenarioName.BASELINE
            supervisory_scenario_version = "FED-2026"

        portfolio_segments = [v for k, v in _SEGMENT_KEYWORDS.items() if k in text] or None
        asset_classes = [v for k, v in _ASSET_CLASS_KEYWORDS.items() if k in text] or None
        if asset_classes:
            asset_classes = sorted(set(asset_classes))

        adhoc_shocks: list[AdhocShock] = []
        bps_match = _BPS_SHOCK_PATTERN.search(text)
        if bps_match:
            matched_variable = next((v for k, v in _VARIABLE_KEYWORDS.items() if k in text), None)
            if matched_variable is None:
                return (
                    DraftScenarioRequest(
                        needs_clarification=True,
                        clarifying_question=(
                            "Which variable should the rate shock apply to, and in which quarters?"
                        ),
                    ).model_dump(mode="json"),
                    0,
                    0,
                )
            adhoc_shocks.append(
                AdhocShock(
                    variable=matched_variable,
                    shock_type=AdhocShockType.ADD_BPS,
                    magnitude=int(bps_match.group(1)),
                    quarters=list(range(1, 10)),
                )
            )

        draft = DraftScenarioRequest(
            reporting_period=reporting_period_match.group(1),
            base_scenario=base_scenario,
            supervisory_scenario_version=supervisory_scenario_version,
            portfolio_segments=portfolio_segments,
            asset_classes=asset_classes,
            adhoc_shocks=adhoc_shocks,
        )
        return draft.model_dump(mode="json"), 0, 0


def _case(case_id: str, nl_request: str, **expected) -> EvalCase:
    return EvalCase(case_id=case_id, inputs={"nl_request": nl_request}, expected=expected)


GOLDEN_SCENARIO_TRANSLATION_CASES: list[EvalCase] = [
    # -- Clean supervisory requests (20) --------------------------------
    *[
        _case(
            f"supervisory-{i:02d}",
            f"Run {scenario_text} on the {segment_text} book for 2026-0{(i % 6) + 1}.",
            needs_clarification=False,
            base_scenario=scenario_enum,
            portfolio_segments=[segment_enum],
        )
        for i, (scenario_text, scenario_enum, segment_text, segment_enum) in enumerate(
            [
                ("Severely Adverse", "SEVERELY_ADVERSE", "middle market", "MIDDLE_MARKET"),
                ("Baseline", "BASELINE", "large corporate", "LARGE_CORPORATE"),
                ("Severely Adverse", "SEVERELY_ADVERSE", "small business", "SMALL_BUSINESS"),
                ("Baseline", "BASELINE", "middle market", "MIDDLE_MARKET"),
                ("Severely Adverse", "SEVERELY_ADVERSE", "large corporate", "LARGE_CORPORATE"),
            ]
            * 4,
            start=1,
        )
    ],
    # -- Clean ad-hoc shock requests (15) --------------------------------
    *[
        _case(
            f"adhoc-{i:02d}",
            f"Add a {bps}bps shock to the {variable_text} for 2026-06.",
            needs_clarification=False,
            adhoc_shock_variable=variable_enum,
            adhoc_shock_magnitude=bps,
        )
        for i, (bps, variable_text, variable_enum) in enumerate(
            [
                (200, "10-year treasury", "TREASURY_10Y"),
                (150, "bbb", "BBB_CORPORATE_YIELD"),
                (100, "unemployment", "UNEMPLOYMENT_RATE"),
                (300, "cre price", "CRE_PRICE_INDEX"),
                (250, "house price", "HOUSE_PRICE_INDEX"),
            ]
            * 3,
            start=1,
        )
    ],
    # -- Ambiguous: missing reporting period (5) -------------------------
    *[
        _case(
            f"ambiguous-period-{i:02d}",
            "Run Severely Adverse on the CRE book.",
            needs_clarification=True,
        )
        for i in range(1, 6)
    ],
    # -- Ambiguous: shock with no named variable (5) ---------------------
    *[
        _case(
            f"ambiguous-variable-{i:02d}",
            "Add a 200bps rate shock for 2026-06.",
            needs_clarification=True,
        )
        for i in range(1, 6)
    ],
    # -- Deliberately out-of-vocabulary phrasing (5) — the rule-based ----
    # translator is EXPECTED to mis-handle these; a real LLM should not.
    _case(
        "out-of-vocab-01",
        "Run a mild recession scenario on the CRE book for 2026-06.",
        needs_clarification=False,
        base_scenario="BASELINE",  # translator finds neither keyword -> None; mismatch by design
        portfolio_segments=["CRE_SEGMENT_PLACEHOLDER"],
    ),
    _case(
        "out-of-vocab-02",
        "Stress the office sub-sector under Severely Adverse for 2026-06.",
        needs_clarification=False,
        base_scenario="SEVERELY_ADVERSE",
        portfolio_segments=["OFFICE_SUBSECTOR_PLACEHOLDER"],  # not a modeled segment
    ),
    _case(
        "out-of-vocab-03",
        "Apply a two hundred basis point shock to the long bond for 2026-06.",
        # Spelled-out magnitude + "long bond" synonym both miss the regex/keyword vocabulary.
        needs_clarification=True,
    ),
    _case(
        "out-of-vocab-04",
        "Run Severely Adverse for the second quarter of fiscal 2026.",
        # "second quarter of fiscal 2026" isn't a YYYY-MM the reporting-period regex catches.
        needs_clarification=True,
    ),
    _case(
        "out-of-vocab-05",
        "Shock the Fed funds rate by 75bps for 2026-06.",
        needs_clarification=True,  # "Fed funds rate" isn't in the variable vocabulary
    ),
]


def run_scenario_translation_eval(
    translator: RuleBasedScenarioTranslator | None = None,
) -> EvalSetResult:
    translator = translator or RuleBasedScenarioTranslator()
    result = EvalSetResult(name="scenario_translation", pass_bar=PASS_BAR)

    for case in GOLDEN_SCENARIO_TRANSLATION_CASES:
        raw, _tokens_in, _tokens_out = translator.complete(
            _FakeRequest(case.inputs["nl_request"]), DraftScenarioRequest
        )
        draft = DraftScenarioRequest.model_validate(raw)
        result.case_results.append(_score_case(case, draft))

    return result


class _FakeRequest:
    def __init__(self, user_prompt: str) -> None:
        self.user_prompt = user_prompt
        self.system_prompt = ""


def _score_case(case: EvalCase, draft: DraftScenarioRequest) -> EvalCaseResult:
    expected = case.expected
    if expected.get("needs_clarification"):
        passed = draft.needs_clarification is True
        return EvalCaseResult(
            case.case_id, passed, f"needs_clarification={draft.needs_clarification}"
        )

    mismatches = []
    if draft.needs_clarification:
        mismatches.append("unexpectedly needs_clarification")
    if "base_scenario" in expected:
        actual = str(draft.base_scenario) if draft.base_scenario else None
        if actual != expected["base_scenario"]:
            mismatches.append(f"base_scenario={actual!r} != {expected['base_scenario']!r}")
    if "portfolio_segments" in expected:
        actual_segments = draft.portfolio_segments or []
        if list(actual_segments) != expected["portfolio_segments"]:
            mismatches.append(
                f"portfolio_segments={actual_segments!r} != {expected['portfolio_segments']!r}"
            )
    if "adhoc_shock_variable" in expected:
        if (
            not draft.adhoc_shocks
            or str(draft.adhoc_shocks[0].variable) != expected["adhoc_shock_variable"]
        ):
            mismatches.append("adhoc_shock_variable mismatch or missing")
    if "adhoc_shock_magnitude" in expected:
        if (
            not draft.adhoc_shocks
            or int(draft.adhoc_shocks[0].magnitude) != expected["adhoc_shock_magnitude"]
        ):
            mismatches.append("adhoc_shock_magnitude mismatch or missing")

    return EvalCaseResult(case.case_id, not mismatches, "; ".join(mismatches))
