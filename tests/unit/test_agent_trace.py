"""Agent Trace Store (C26) tests: write/read roundtrip and the
`count_tool_calls` helper the Policy Enforcement Point uses to enforce
`ToolPolicy.max_calls_per_session`. See 02-design-document.md §2.11.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fry14_engine.agent_trace.logger import AgentTraceLogger
from fry14_engine.agent_trace.models import AgentTraceEventType
from fry14_engine.common.enums import AgentId
from fry14_engine.db import bootstrap, get_connection


@pytest.fixture
def logger(tmp_db_path: Path) -> AgentTraceLogger:
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    return AgentTraceLogger(con)


def test_log_and_read_session_roundtrip(logger: AgentTraceLogger):
    logger.log(
        AgentTraceEventType.USER_REQUEST,
        session_id="sess-1",
        agent_id=str(AgentId.AG1_PIPELINE_OPERATIONS),
        on_behalf_of="alice",
        payload_ref="run the pipeline",
    )
    logger.log(
        AgentTraceEventType.TOOL_CALL,
        session_id="sess-1",
        agent_id=str(AgentId.AG1_PIPELINE_OPERATIONS),
        on_behalf_of="alice",
        tool_name="ingest_batch",
    )

    events = logger.read_session("sess-1")
    assert [e.event_type for e in events] == [
        AgentTraceEventType.USER_REQUEST,
        AgentTraceEventType.TOOL_CALL,
    ]
    assert events[0].payload_ref == "run the pipeline"
    assert events[1].tool_name == "ingest_batch"
    assert events[1].event_timestamp is not None


def test_read_session_is_scoped_to_session_id(logger: AgentTraceLogger):
    logger.log(
        AgentTraceEventType.USER_REQUEST,
        session_id="sess-a",
        agent_id=str(AgentId.AG1_PIPELINE_OPERATIONS),
        on_behalf_of="alice",
    )
    logger.log(
        AgentTraceEventType.USER_REQUEST,
        session_id="sess-b",
        agent_id=str(AgentId.AG1_PIPELINE_OPERATIONS),
        on_behalf_of="bob",
    )
    assert len(logger.read_session("sess-a")) == 1
    assert len(logger.read_session("sess-b")) == 1


def test_count_tool_calls_only_counts_tool_call_events(logger: AgentTraceLogger):
    logger.log(
        AgentTraceEventType.TOOL_CALL,
        session_id="sess-1",
        agent_id=str(AgentId.AG1_PIPELINE_OPERATIONS),
        on_behalf_of="alice",
        tool_name="ingest_batch",
    )
    logger.log(
        AgentTraceEventType.TOOL_RESULT,
        session_id="sess-1",
        agent_id=str(AgentId.AG1_PIPELINE_OPERATIONS),
        on_behalf_of="alice",
        tool_name="ingest_batch",
    )
    logger.log(
        AgentTraceEventType.TOOL_CALL,
        session_id="sess-1",
        agent_id=str(AgentId.AG1_PIPELINE_OPERATIONS),
        on_behalf_of="alice",
        tool_name="aggregate_schedules",
    )

    assert logger.count_tool_calls("sess-1", "ingest_batch") == 1
    assert logger.count_tool_calls("sess-1", "aggregate_schedules") == 1
    assert logger.count_tool_calls("sess-1", "never_called") == 0
