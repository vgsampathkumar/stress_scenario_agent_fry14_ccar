-- Agent governance: tool policy, agent proposals, agent trace events, and
-- grounded narratives. See 02-design-document.md §2.11 (ToolPolicy,
-- AgentProposal, AgentTraceEvent, GroundedNarrative).
--
-- RBAC permissions and agent identifiers are enforced as free-text VARCHARs
-- here (not FK'd to a permissions/agents table) because they are governed
-- as Python enums (common/enums.py: Permission, AgentId), not DB rows — see
-- schemas/009_rbac.sql's own note that the role->permission matrix is
-- populated by application code, not seeded SQL.

CREATE TABLE IF NOT EXISTS agent_governance.tool_policy (
    tool_name              VARCHAR PRIMARY KEY,
    required_permission       VARCHAR NOT NULL,
    autonomy                    VARCHAR NOT NULL
        CHECK (autonomy IN ('AUTONOMOUS', 'CONFIRM', 'PROPOSE', 'HUMAN_ONLY', 'PROHIBITED')),
    allowed_agents                VARCHAR[],         -- list of agent_id strings, e.g. ['AG-1']
    max_calls_per_session            INTEGER,
    version                            VARCHAR NOT NULL DEFAULT '1.0.0',
    updated_at                           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_governance.tool_policy_condition (
    tool_name              VARCHAR NOT NULL REFERENCES agent_governance.tool_policy (tool_name),
    condition_id             INTEGER NOT NULL,
    expression                 VARCHAR NOT NULL,
    escalate_to                  VARCHAR NOT NULL
        CHECK (escalate_to IN ('AUTONOMOUS', 'CONFIRM', 'PROPOSE', 'HUMAN_ONLY', 'PROHIBITED')),
    PRIMARY KEY (tool_name, condition_id)
);

CREATE TABLE IF NOT EXISTS agent_governance.agent_proposal (
    proposal_id              VARCHAR PRIMARY KEY,   -- uuid
    proposing_agent            VARCHAR NOT NULL,
    session_id                   VARCHAR NOT NULL,
    proposal_type                  VARCHAR NOT NULL
        CHECK (proposal_type IN ('REMEDIATION_RULE', 'CONTRACT_AMENDMENT',
                                  'PUBLISH_OVERRIDE', 'NARRATIVE_RELEASE', 'SOURCE_TICKET')),
    payload                            VARCHAR NOT NULL,   -- JSON blob, never applied directly
    evidence                             VARCHAR,            -- JSON array of refs (quarantine/query/run ids)
    rationale                              VARCHAR,
    required_permission                      VARCHAR NOT NULL,
    requires_four_eyes                         BOOLEAN NOT NULL DEFAULT TRUE,
    status                                       VARCHAR NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED')),
    decided_by                                     VARCHAR,
    decision_reason                                  VARCHAR,
    created_at                                         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_at                                           TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_governance.agent_trace_event (
    event_id                 VARCHAR PRIMARY KEY,   -- uuid
    session_id                 VARCHAR NOT NULL,
    agent_id                     VARCHAR NOT NULL,
    on_behalf_of                   VARCHAR NOT NULL,   -- user_id or 'SYSTEM_SCHEDULER'
    event_type                       VARCHAR NOT NULL
        CHECK (event_type IN ('USER_REQUEST', 'PLAN', 'TOOL_CALL', 'TOOL_RESULT',
                               'POLICY_DECISION', 'PROPOSAL', 'APPROVAL', 'RESPONSE',
                               'GROUNDING_CHECK', 'ERROR')),
    payload_ref                        VARCHAR,            -- pointer + hash; payloads are PII-free
    model_id                             VARCHAR,
    prompt_template_version                 VARCHAR,
    tokens_in                                 INTEGER,
    tokens_out                                  INTEGER,
    latency_ms                                    INTEGER,
    pipeline_run_id                                 VARCHAR,
    scenario_run_id                                   VARCHAR,
    event_timestamp                                     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_trace_session ON agent_governance.agent_trace_event (session_id);

CREATE TABLE IF NOT EXISTS agent_governance.grounded_narrative (
    narrative_id              VARCHAR PRIMARY KEY,   -- uuid
    session_id                  VARCHAR NOT NULL,
    pipeline_run_id                VARCHAR,
    scenario_run_id                  VARCHAR,
    template_text                      VARCHAR NOT NULL,   -- contains {{run:<id>.field}} bindings
    rendered_text                        VARCHAR,
    grounding_status                       VARCHAR NOT NULL DEFAULT 'FAILED'
        CHECK (grounding_status IN ('PASSED', 'FAILED')),
    approval_status                          VARCHAR NOT NULL DEFAULT 'DRAFT'
        CHECK (approval_status IN ('DRAFT', 'APPROVED', 'REJECTED')),
    released_by                                VARCHAR,
    created_at                                   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    released_at                                    TIMESTAMP
);
