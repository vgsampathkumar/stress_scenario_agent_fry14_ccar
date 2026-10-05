# Legacy v1.0 planning docs (superseded)

These four documents are the **v1.0 "Governed Financial Data Product Engine"**
spec — the deterministic-only design, before the agentic layer was added.
They are preserved here as a historical record of how the design evolved,
but they are **not current**. The canonical, actively-maintained docs are at
the repo root:

- `../../requirements.md`
- `../../01-approach-paper.md`
- `../../02-design-document.md`
- `../../03-implementation-plan.md`

The v2.0 docs explicitly supersede these; Phases 0–7 of the deterministic
engine are unchanged in substance between the two versions, so code already
built against this v1.0 spec remains valid. The delta is the agentic layer
(5 agents, MCP tool server, policy enforcement, stress engine, approval
queue, evaluation harness) added on top, starting at Phase 8.
