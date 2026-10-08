-- Agent Runtime (C17): checkpointed session state for the supervisor/
-- specialist graph — session status, step/tool-call/token counters
-- against `RunLimits`, and a JSON checkpoint blob (plan + intermediate
-- results + any pending confirmation) so a session can pause for human
-- confirmation/approval and resume without re-running completed steps.
-- See 02-design-document.md §3.12.

CREATE TABLE IF NOT EXISTS agent_governance.agent_session (
    session_id                 VARCHAR PRIMARY KEY,
    agent_id                     VARCHAR NOT NULL,
    on_behalf_of                   VARCHAR NOT NULL,
    user_role                        VARCHAR NOT NULL,
    model_id                           VARCHAR NOT NULL,
    prompt_template_version               VARCHAR NOT NULL,
    status                                  VARCHAR NOT NULL DEFAULT 'IN_PROGRESS'
        CHECK (status IN ('IN_PROGRESS', 'AWAITING_CONFIRMATION', 'COMPLETED',
                           'LIMIT_REACHED', 'ERROR')),
    step_count                                INTEGER NOT NULL DEFAULT 0,
    tool_call_count                             INTEGER NOT NULL DEFAULT 0,
    tokens_used                                   INTEGER NOT NULL DEFAULT 0,
    max_steps                                       INTEGER NOT NULL,
    max_tool_calls                                    INTEGER NOT NULL,
    max_tokens                                          INTEGER NOT NULL,
    checkpoint                                            VARCHAR,   -- JSON: plan + intermediate results
    created_at                                              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                                                TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
