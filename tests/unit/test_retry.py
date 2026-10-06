from __future__ import annotations

import pytest

from fry14_engine.orchestrator.retry import RetryExhaustedError, retry_on_transient_error


class _FlakyError(Exception):
    pass


class _OtherError(Exception):
    pass


def test_succeeds_on_first_try_when_no_error():
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    result = retry_on_transient_error(fn, max_attempts=3, backoff_seconds=0)
    assert result == "ok"
    assert len(calls) == 1


def test_recovers_after_transient_failures():
    attempts = {"count": 0}

    def fn():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise _FlakyError("transient")
        return "recovered"

    result = retry_on_transient_error(
        fn, max_attempts=5, backoff_seconds=0, retryable_exceptions=(_FlakyError,)
    )
    assert result == "recovered"
    assert attempts["count"] == 3


def test_gives_up_after_max_attempts():
    attempts = {"count": 0}

    def fn():
        attempts["count"] += 1
        raise _FlakyError("always fails")

    with pytest.raises(RetryExhaustedError) as exc_info:
        retry_on_transient_error(
            fn, max_attempts=3, backoff_seconds=0, retryable_exceptions=(_FlakyError,)
        )
    assert attempts["count"] == 3
    assert exc_info.value.attempts == 3
    assert isinstance(exc_info.value.last_error, _FlakyError)


def test_non_retryable_exception_propagates_immediately():
    attempts = {"count": 0}

    def fn():
        attempts["count"] += 1
        raise _OtherError("not transient")

    with pytest.raises(_OtherError):
        retry_on_transient_error(
            fn, max_attempts=5, backoff_seconds=0, retryable_exceptions=(_FlakyError,)
        )
    assert attempts["count"] == 1  # no retries for a non-retryable exception
