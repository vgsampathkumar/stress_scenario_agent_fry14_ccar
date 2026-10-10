"""Evaluation Harness (C30) tests — running every golden set is how this
suite becomes a release gate (requirements.md AG-GOV-4): any change to a
tool schema, policy config, or the (illustrative) translators that drops
a set below its pass bar fails CI. See 02-design-document.md §3.21.

Three of the five sets (grounding, guardrails, prompt injection) exercise
real, deterministic production code and are expected to clear their bar
at 100%. The other two (scenario translation, triage) score an
*illustrative* rule-based stand-in — see each module's own scope note —
so this suite asserts their actual, honestly-measured pass rate and
specific known failures, not an inflated "it passed" result. A real
model swapped in later must be re-run against these same golden sets
before release (AG-GOV-2).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fry14_engine.db import bootstrap, get_connection
from fry14_engine.evaluation.grounding_eval import run_grounding_eval
from fry14_engine.evaluation.guardrails import run_guardrails_eval
from fry14_engine.evaluation.prompt_injection import run_prompt_injection_eval
from fry14_engine.evaluation.scenario_translation import (
    GOLDEN_SCENARIO_TRANSLATION_CASES,
    run_scenario_translation_eval,
)
from fry14_engine.evaluation.triage import GOLDEN_TRIAGE_CASES, run_triage_eval


@pytest.fixture
def connection(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    yield con
    con.close()


def test_scenario_translation_golden_set_has_at_least_fifty_cases():
    assert len(GOLDEN_SCENARIO_TRANSLATION_CASES) >= 50


def test_scenario_translation_eval_matches_known_illustrative_score():
    result = run_scenario_translation_eval()
    assert result.total_count >= 50
    # The illustrative rule-based translator is known to miss exactly the
    # 3 deliberately out-of-vocabulary cases that use phrasing outside its
    # keyword list — a real LLM should clear all of these.
    failed_ids = {f.case_id for f in result.failures}
    assert failed_ids == {"out-of-vocab-01", "out-of-vocab-02", "out-of-vocab-03"}
    assert result.pass_rate == pytest.approx(0.94, abs=0.01)
    assert result.meets_bar is False  # honestly reported, not force-passed


def test_triage_golden_set_has_at_least_ten_cases():
    assert len(GOLDEN_TRIAGE_CASES) >= 10


def test_triage_eval_clears_its_bar():
    result = run_triage_eval()
    assert result.meets_bar is True
    assert result.pass_rate == 1.0


def test_grounding_eval_clears_its_bar():
    result = run_grounding_eval()
    assert result.meets_bar is True
    assert result.pass_rate == 1.0


def test_guardrails_eval_clears_its_bar(connection):
    result = run_guardrails_eval(connection)
    assert result.meets_bar is True
    assert result.pass_rate == 1.0
    assert result.total_count >= 5


def test_prompt_injection_eval_clears_its_bar(connection):
    result = run_prompt_injection_eval(connection)
    assert result.meets_bar is True
    assert result.pass_rate == 1.0
