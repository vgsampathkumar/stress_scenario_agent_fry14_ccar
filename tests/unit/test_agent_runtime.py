"""Agent Runtime (C17) tests: session lifecycle, checkpointing, hard
per-session limits, and structured-output validation with one retry then
escalation. See 02-design-document.md §3.12.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from fry14_engine.agent_runtime.models import (
    LlmCompletionRequest,
    RunLimits,
    SessionStatus,
    StructuredOutputInvalidError,
)
from fry14_engine.agent_runtime.runtime import AgentRuntime
from fry14_engine.agent_trace.logger import AgentTraceLogger
from fry14_engine.common.enums import AgentId, RoleName
from fry14_engine.db import bootstrap, get_connection


class _Hypothesis(BaseModel):
    reason_code: str
    confidence: float


class _AlwaysValidLlmClient:
    model_id = "fake-model"
    prompt_template_version = "1.0.0"

    def complete(self, request, response_schema):
        return {"reason_code": "MISSING_CREDIT_SCORE", "confidence": 0.9}, 10, 5


class _AlwaysInvalidLlmClient:
    model_id = "fake-model"
    prompt_template_version = "1.0.0"

    def __init__(self):
        self.call_count = 0

    def complete(self, request, response_schema):
        self.call_count += 1
        return {"reason_code": "X"}, 10, 5  # missing required `confidence`


class _RecoversOnSecondAttemptLlmClient:
    model_id = "fake-model"
    prompt_template_version = "1.0.0"

    def __init__(self):
        self.call_count = 0

    def complete(self, request, response_schema):
        self.call_count += 1
        if self.call_count == 1:
            return {"reason_code": "X"}, 10, 5  # invalid
        return {"reason_code": "MISSING_CREDIT_SCORE", "confidence": 0.5}, 10, 5


@pytest.fixture
def connection(tmp_db_path: Path):
    bootstrap(tmp_db_path)
    con = get_connection(tmp_db_path)
    yield con
    con.close()


@pytest.fixture
def runtime(connection) -> AgentRuntime:
    return AgentRuntime(connection)


def test_start_session_persists_and_logs_user_request(runtime: AgentRuntime):
    session = runtime.start_session(
        AgentId.AG1_PIPELINE_OPERATIONS, "alice", RoleName.DATA_ENGINEER, "model-1", "1.0.0"
    )
    assert session.status == SessionStatus.IN_PROGRESS
    read_back = runtime.read_session(session.session_id)
    assert read_back == session


def test_record_step_increments_and_merges_checkpoint(runtime: AgentRuntime):
    session = runtime.start_session(
        AgentId.AG1_PIPELINE_OPERATIONS, "alice", RoleName.DATA_ENGINEER, "model-1", "1.0.0"
    )
    session = runtime.record_step(session, {"plan": ["ingest"]})
    session = runtime.record_step(session, {"ingestion_done": True})
    assert session.step_count == 2
    assert session.checkpoint == {"plan": ["ingest"], "ingestion_done": True}


def test_record_step_beyond_max_steps_reaches_limit(runtime: AgentRuntime):
    session = runtime.start_session(
        AgentId.AG1_PIPELINE_OPERATIONS,
        "alice",
        RoleName.DATA_ENGINEER,
        "model-1",
        "1.0.0",
        limits=RunLimits(max_steps=2),
    )
    session = runtime.record_step(session, {"a": 1})
    session = runtime.record_step(session, {"b": 2})
    assert session.status == SessionStatus.IN_PROGRESS
    session = runtime.record_step(session, {"c": 3})
    assert session.status == SessionStatus.LIMIT_REACHED


def test_record_step_is_a_noop_once_limit_reached(runtime: AgentRuntime):
    session = runtime.start_session(
        AgentId.AG1_PIPELINE_OPERATIONS,
        "alice",
        RoleName.DATA_ENGINEER,
        "model-1",
        "1.0.0",
        limits=RunLimits(max_steps=1),
    )
    session = runtime.record_step(session, {"a": 1})
    session = runtime.record_step(session, {"b": 2})
    assert session.status == SessionStatus.LIMIT_REACHED
    unchanged = runtime.record_step(session, {"c": 3})
    assert unchanged.step_count == session.step_count
    assert unchanged.checkpoint == session.checkpoint


def test_record_tool_call_beyond_max_reaches_limit(runtime: AgentRuntime):
    session = runtime.start_session(
        AgentId.AG1_PIPELINE_OPERATIONS,
        "alice",
        RoleName.DATA_ENGINEER,
        "model-1",
        "1.0.0",
        limits=RunLimits(max_tool_calls=1),
    )
    session = runtime.record_tool_call(session)
    session = runtime.record_tool_call(session)
    assert session.status == SessionStatus.LIMIT_REACHED


def test_record_tool_call_is_a_noop_once_limit_reached(runtime: AgentRuntime):
    session = runtime.start_session(
        AgentId.AG1_PIPELINE_OPERATIONS,
        "alice",
        RoleName.DATA_ENGINEER,
        "model-1",
        "1.0.0",
        limits=RunLimits(max_tool_calls=1),
    )
    session = runtime.record_tool_call(session)
    session = runtime.record_tool_call(session)
    assert session.status == SessionStatus.LIMIT_REACHED
    unchanged = runtime.record_tool_call(session)
    assert unchanged.tool_call_count == session.tool_call_count


def test_record_tokens_is_a_noop_once_limit_reached(runtime: AgentRuntime):
    session = runtime.start_session(
        AgentId.AG1_PIPELINE_OPERATIONS,
        "alice",
        RoleName.DATA_ENGINEER,
        "model-1",
        "1.0.0",
        limits=RunLimits(max_tokens=10),
    )
    session = runtime.record_tokens(session, tokens_in=6, tokens_out=6)
    assert session.status == SessionStatus.LIMIT_REACHED
    unchanged = runtime.record_tokens(session, tokens_in=100, tokens_out=100)
    assert unchanged.tokens_used == session.tokens_used


def test_record_tokens_beyond_max_reaches_limit(runtime: AgentRuntime):
    session = runtime.start_session(
        AgentId.AG1_PIPELINE_OPERATIONS,
        "alice",
        RoleName.DATA_ENGINEER,
        "model-1",
        "1.0.0",
        limits=RunLimits(max_tokens=100),
    )
    session = runtime.record_tokens(session, tokens_in=60, tokens_out=60)
    assert session.status == SessionStatus.LIMIT_REACHED
    assert session.tokens_used == 120


def test_complete_structured_succeeds_on_first_attempt(runtime: AgentRuntime):
    session = runtime.start_session(
        AgentId.AG2_DATA_QUALITY_TRIAGE, "alice", RoleName.DATA_ENGINEER, "model-1", "1.0.0"
    )
    request = LlmCompletionRequest(system_prompt="sys", user_prompt="usr")
    session, parsed = runtime.complete_structured(
        session, _AlwaysValidLlmClient(), request, _Hypothesis
    )
    assert parsed.reason_code == "MISSING_CREDIT_SCORE"
    assert session.tokens_used == 15


def test_complete_structured_retries_once_then_succeeds(runtime: AgentRuntime):
    session = runtime.start_session(
        AgentId.AG2_DATA_QUALITY_TRIAGE, "alice", RoleName.DATA_ENGINEER, "model-1", "1.0.0"
    )
    client = _RecoversOnSecondAttemptLlmClient()
    request = LlmCompletionRequest(system_prompt="sys", user_prompt="usr")
    session, parsed = runtime.complete_structured(session, client, request, _Hypothesis)
    assert client.call_count == 2
    assert parsed.confidence == 0.5


def test_complete_structured_raises_after_second_failure(runtime: AgentRuntime):
    session = runtime.start_session(
        AgentId.AG2_DATA_QUALITY_TRIAGE, "alice", RoleName.DATA_ENGINEER, "model-1", "1.0.0"
    )
    client = _AlwaysInvalidLlmClient()
    request = LlmCompletionRequest(system_prompt="sys", user_prompt="usr")
    with pytest.raises(StructuredOutputInvalidError):
        runtime.complete_structured(session, client, request, _Hypothesis)
    assert client.call_count == 2

    final = runtime.read_session(session.session_id)
    assert final.status == SessionStatus.ERROR


def test_await_confirmation_then_resume(runtime: AgentRuntime):
    session = runtime.start_session(
        AgentId.AG3_STRESS_SCENARIO, "dave", RoleName.FINANCE, "model-1", "1.0.0"
    )
    session = runtime.await_confirmation(session)
    assert session.status == SessionStatus.AWAITING_CONFIRMATION
    session = runtime.resume(session)
    assert session.status == SessionStatus.IN_PROGRESS


def test_finish_sets_completed_status(runtime: AgentRuntime):
    session = runtime.start_session(
        AgentId.AG1_PIPELINE_OPERATIONS, "alice", RoleName.DATA_ENGINEER, "model-1", "1.0.0"
    )
    finished = runtime.finish(session)
    assert finished.status == SessionStatus.COMPLETED
    assert runtime.read_session(session.session_id).status == SessionStatus.COMPLETED


def test_read_unknown_session_returns_none(runtime: AgentRuntime):
    assert runtime.read_session("nonexistent") is None


def test_start_session_logs_a_user_request_trace_event(runtime: AgentRuntime, connection):
    session = runtime.start_session(
        AgentId.AG1_PIPELINE_OPERATIONS, "alice", RoleName.DATA_ENGINEER, "model-1", "2.3.0"
    )
    events = AgentTraceLogger(connection).read_session(session.session_id)
    assert len(events) == 1
    assert events[0].model_id == "model-1"
    assert events[0].prompt_template_version == "2.3.0"
