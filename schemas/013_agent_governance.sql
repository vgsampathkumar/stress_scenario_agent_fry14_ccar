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
    requested_by                   VARCHAR NOT NULL,   -- user who initiated the session; four-eyes
                                                         -- compares the approver against this, not
                                                         -- against proposing_agent (the agent holds
                                                         -- no identity of its own to approve/reject)
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
    tool_name                          VARCHAR,            -- set on TOOL_CALL/TOOL_RESULT/
                                                             -- POLICY_DECISION events; lets the PEP
                                                             -- enforce ToolPolicy.max_calls_per_session
                                                             -- without parsing payload_ref
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

-- Tool catalog seed data (requirements.md §3.3). Illustrative agent
-- ownership per §3.1/§3.2: AG-1 (pipeline ops), AG-2 (DQ triage), AG-3
-- (stress scenario), AG-5 (data product concierge). `get_catalog_status`
-- and `get_lineage` are "cross-cutting" per the catalog table — every
-- agent may read them. `apply_remediation` has an empty allowed_agents
-- list: HUMAN_ONLY per §3.4, never callable by any agent regardless of
-- autonomy. See 02-design-document.md §3.13-§3.14.
INSERT INTO agent_governance.tool_policy
    (tool_name, required_permission, autonomy, allowed_agents, max_calls_per_session)
SELECT * FROM (VALUES
    ('ingest_batch', 'RUN_PIPELINE', 'AUTONOMOUS', ['AG-1'], 10),
    ('ingest_event', 'RUN_PIPELINE', 'AUTONOMOUS', ['AG-1'], 10),
    ('validate_against_contract', 'RUN_PIPELINE', 'AUTONOMOUS', ['AG-1'], 10),
    ('get_quarantine_summary', 'REMEDIATE_QUARANTINE', 'AUTONOMOUS', ['AG-2'], NULL),
    ('propose_remediation', 'REMEDIATE_QUARANTINE', 'PROPOSE', ['AG-2'], 10),
    ('apply_remediation', 'REMEDIATE_QUARANTINE', 'HUMAN_ONLY', [], NULL),
    ('propose_contract_change', 'MANAGE_CONTRACTS', 'PROPOSE', ['AG-2'], 5),
    ('calculate_risk_metrics', 'RUN_PIPELINE', 'AUTONOMOUS', ['AG-1'], 10),
    ('aggregate_schedules', 'RUN_PIPELINE', 'AUTONOMOUS', ['AG-1'], 10),
    ('publish_data_product', 'PUBLISH_DATA_PRODUCT', 'AUTONOMOUS', ['AG-1'], 10),
    ('build_scenario_spec', 'RUN_STRESS_SCENARIO', 'AUTONOMOUS', ['AG-3'], 20),
    ('run_stress_scenario', 'RUN_STRESS_SCENARIO', 'CONFIRM', ['AG-3'], 5),
    ('query_sandbox', 'QUERY_SANDBOX_READ', 'AUTONOMOUS', ['AG-5'], NULL),
    ('get_catalog_status', 'VIEW_CATALOG', 'AUTONOMOUS',
     ['AG-1', 'AG-2', 'AG-3', 'AG-4', 'AG-5'], NULL),
    ('get_lineage', 'VIEW_CATALOG', 'AUTONOMOUS',
     ['AG-1', 'AG-2', 'AG-3', 'AG-4', 'AG-5'], NULL)
) AS v(tool_name, required_permission, autonomy, allowed_agents, max_calls_per_session)
WHERE NOT EXISTS (SELECT 1 FROM agent_governance.tool_policy WHERE tool_name = v.tool_name);

-- Conditional escalation example from design doc §3.14: publish is
-- AUTONOMOUS by default but escalates to PROPOSE (human approval) when
-- the run's DQ pass rate is below the catalog threshold.
INSERT INTO agent_governance.tool_policy_condition (tool_name, condition_id, expression, escalate_to)
SELECT * FROM (VALUES
    ('publish_data_product', 1, 'dq_pass_rate_below_threshold', 'PROPOSE')
) AS v(tool_name, condition_id, expression, escalate_to)
WHERE NOT EXISTS (
    SELECT 1 FROM agent_governance.tool_policy_condition
    WHERE tool_name = v.tool_name AND condition_id = v.condition_id
);

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
