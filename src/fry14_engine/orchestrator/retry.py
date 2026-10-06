"""Transient-failure retry helper for the Orchestrator (C16). See
02-design-document.md §3.11 ("handles retries for transient failures").
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class RetryExhaustedError(Exception):
    def __init__(self, attempts: int, last_error: Exception) -> None:
        super().__init__(f"Gave up after {attempts} attempt(s): {last_error}")
        self.attempts = attempts
        self.last_error = last_error


def retry_on_transient_error(
    fn: Callable[[], T],
    max_attempts: int = 3,
    backoff_seconds: float = 0.1,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> T:
    """Call `fn()`, retrying up to `max_attempts` times (with linear
    backoff) if it raises one of `retryable_exceptions`. Any other
    exception propagates immediately — only the caller knows which errors
    are genuinely transient versus a real defect to surface right away.
    """
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except retryable_exceptions as exc:  # noqa: BLE001 - re-raised via RetryExhaustedError
            last_error = exc
            if attempt < max_attempts:
                time.sleep(backoff_seconds * attempt)
    assert last_error is not None  # the loop only exits via return or this path
    raise RetryExhaustedError(max_attempts, last_error)
