

from __future__ import annotations
import os
import time
import functools
from typing import Callable, TypeVar
from app.audits import audit_logger

MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))
BASE_DELAY = float(os.getenv("RETRY_BASE_DELAY_SECONDS", "0.3"))

T = TypeVar("T")


class RazorpayCallFailed(Exception):
    """Raised when all retries are exhausted -- the orchestrator catches
    this and turns it into a clean, logged, blocked result rather than a
    500 error bubbling up to the caller."""


def call_with_retry(fn: Callable[[], T], *, tool: str, actor: str, params: dict) -> T:
    """Call fn() with bounded retries. Logs each retry attempt as an audit
    trace, then raises RazorpayCallFailed if every attempt fails."""
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 2):  
        try:
            return fn()
        except Exception as exc: 
            last_exc = exc
            if attempt <= MAX_RETRIES:
                audit_logger.log(
                    actor=actor,
                    tool=f"retry_trace:{tool}",
                    params=params,
                    decision="blocked",
                    reason=f"Attempt {attempt} failed ({repr(exc)}); retrying in {BASE_DELAY * attempt:.1f}s",
                )
                time.sleep(BASE_DELAY * attempt)
    raise RazorpayCallFailed(repr(last_exc))
