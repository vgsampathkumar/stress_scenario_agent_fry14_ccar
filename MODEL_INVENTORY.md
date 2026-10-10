# Model Inventory Entry — FR Y-14 Governed Agentic Data Product Engine

Aligned with SR 11-7 ("Guidance on Model Risk Management") principles: purpose,
scope, limitations, and controls are documented before any model is relied
upon, and re-evaluation is triggered by any material change. See
`02-design-document.md` §7 and requirements.md AG-GOV-1–AG-GOV-5.

## 1. What is — and isn't — a "model" here

This system has two categorically different kinds of numeric authority, and
the distinction is the whole point of the architecture:

| Component | Nature | Model risk status |
|---|---|---|
| Risk Metric Engine (EAD/EL/RWA), Stress Engine, Aggregation Engine, Grounding Checker, Policy Enforcement Point | Deterministic, versioned, unit-tested code | **Not a model** under SR 11-7 (no estimation, no judgment, fully reproducible from `calc_engine_version`/`regulatory_parameter_version`/`input_hash`) |
| `LlmClient` (AG-1's narration is template-only; AG-2/AG-3/AG-4/AG-5's drafting/translation steps) | An LLM, pluggable behind a `Protocol` | **Is a model** — this entry's actual subject |

**As of Phase 12, no concrete `LlmClient` implementation exists in this
repository.** `agent_runtime/models.py` defines the `Protocol` every agent
codes against; nothing in `src/` implements it with a real API call (see that
module's own scope note, repeated in every phase's README entry since Phase
9). The evaluation harness (`src/fry14_engine/evaluation/`) scores two
illustrative, deliberately simple rule-based stand-ins — not models — against
golden sets, to prove the harness itself is a real gate before any model is
plugged in. **This entry therefore documents the governance framework a real
model must pass through, not a specific deployed model.**

## 2. Purpose and intended use

An LLM plugged into `LlmClient` would be used for exactly four narrow,
structurally-constrained tasks, each gated by deterministic code before or
after the model call:

1. **AG-3 scenario translation** — convert a natural-language stress request
   into a `DraftScenarioRequest` (structured output). The model never
   computes a stressed metric; `build_scenario_spec` and the Stress Engine
   (Phase 8, fully deterministic) do that.
2. **AG-2 root-cause triage** — form a hypothesis over `get_quarantine_summary`
   cluster statistics (never raw records). The model never edits data;
   every hypothesis becomes an `AgentProposal` requiring human approval.
3. **AG-4 narrative drafting** — write a `{{token}}`-bound template. The model
   never writes a number directly into the delivered text; the Grounding
   Checker (Phase 11, fully deterministic) resolves every binding and blocks
   release on any unbound number.
4. **AG-5 concierge question answering** — pick `reporting_period` and
   `schema_version` for the existing typed `query_sandbox` call (no SQL
   generation surface at all). The model never sees or returns raw PII; the
   structured output schema has no field for it.

## 3. Limitations

- Translation/triage/narrative-drafting/concierge accuracy is **only as good
  as the golden-set evaluation run against the actual deployed model** —
  this entry's own evaluation results (§5) are against illustrative
  stand-ins, not a production model, and must be re-run before any real
  model goes live (AG-GOV-2).
- The model has no tool-execution authority of its own — every tool call is
  re-evaluated by the Policy Enforcement Point against the *calling user's*
  RBAC permissions, never the model's judgment of what's appropriate.
- The model cannot see raw PII at any point — PII fields are hashed before
  any governed/quarantine record exists, and the PII Egress Guard
  (`pii_egress/guard.py`) is a second, independent check on every outbound
  payload.
- Session limits (max steps / tool calls / tokens) bound worst-case runaway
  behavior; hitting any limit ends the session with a partial, clearly
  marked result rather than continuing silently.

## 4. Controls

| Control | Component | What it prevents |
|---|---|---|
| Deterministic validation before execution | `build_scenario_spec`, contract validation | A malformed/implausible draft never reaches the Stress Engine |
| Policy Enforcement Point | `policy/pep.py` | Any tool call outside the calling user's RBAC ∩ the agent's allowlist ∩ the tool's autonomy level |
| Approval Queue (four-eyes) | `approval_queue/service.py` | A single compromised or mistaken session from applying a remediation, contract change, or narrative release unilaterally |
| Numeric Grounding Checker | `grounding/checker.py` | Any number in a released narrative that doesn't trace to a real tool output |
| PII Egress Guard | `pii_egress/guard.py` | SSN/EIN-shaped strings reaching an outbound model payload |
| Agent Trace Store | `agent_trace/` | Every session (request, plan, tool calls, policy decisions, model id, prompt template version) being unreconstructable after the fact |
| Session hard limits | `agent_runtime/runtime.py` | Unbounded cost/runaway tool-calling from a single session |
| Evaluation harness | `evaluation/` | A model/prompt/tool-schema/policy change shipping without clearing its golden-set bar |

## 5. Evaluation results (illustrative stand-ins — see §1)

Run via `pytest tests/integration/test_evaluation_harness.py -v`; wired into
CI as a release gate (`.github/workflows/ci.yml` runs the full suite on every
push/PR).

| Set | Pass bar | Illustrative result | Notes |
|---|---|---|---|
| Scenario translation | ≥95% exact match | **94%** (47/50) — *below bar* | `RuleBasedScenarioTranslator` is a keyword/regex stand-in, not a model; the 3 misses are deliberately out-of-vocabulary phrasing (spelled-out numbers, unmodeled sub-segments, non-standard date phrasing). This is the harness correctly refusing to rubber-stamp an imperfect candidate. |
| Triage | ≥90% correct root cause + source | **100%** (18/18) | `RuleBasedTriageTranslator` is a frequency-concentration heuristic, not a model. |
| Grounding | 100% bound figures, 0 unbound released | **100%** (7/7) | Exercises the real, production `GroundingChecker` — not a stand-in. |
| Guardrails | 100% denied and logged | **100%** (6/6) | Exercises the real PEP, PII Egress Guard, and Approval Queue — not a stand-in. |
| Prompt injection | No change in tool calls vs. clean baseline | **100%** (3/3) | Injects instruction-like text into a free-text, non-hashed field; the deterministic pipeline never parses field content as instructions. |

**Re-evaluation trigger**: per AG-GOV-2, any change to a model ID, prompt
template version, tool schema, or policy config requires re-running this
entire harness before release — the same mechanism that would govern a real
model, already wired into CI today against the illustrative stand-ins.

## 6. Ownership and review

- **Model owner (proposed)**: Risk/Quant team (stress scenario translation,
  narrative accuracy) jointly with Data Engineering (triage, concierge).
- **Validation**: this document + the evaluation harness constitute the
  initial validation artifact; a real model's first deployment requires an
  independent model risk review per the institution's SR 11-7 program before
  this entry can be marked "validated" rather than "framework only."
- **Next review trigger**: first concrete `LlmClient` implementation, or any
  change listed in §5's re-evaluation trigger.
