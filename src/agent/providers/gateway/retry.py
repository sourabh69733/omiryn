"""Retries provider requests that failed before doing any work.

Only transient failures are retried: the connection could not be made, or the provider said
it is busy or briefly down. A slow response (read timeout) is not retried, since the model
may already be generating and a second request would double the wait and the cost.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_RETRYABLE_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError)
_BACKOFF_SECONDS = (1.0, 3.0)
_MAX_RETRY_AFTER_SECONDS = 10.0


def provider_retries() -> int:
    try:
        return max(0, int(os.getenv("AGENT_PROVIDER_RETRIES", "2")))
    except ValueError:
        return 2


async def post_with_retry(client: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
    """POST, retrying transient failures; the final response or error is returned as-is."""
    retries = provider_retries()
    for attempt in range(retries + 1):
        last_attempt = attempt == retries
        try:
            response = await client.post(url, **kwargs)
        except _RETRYABLE_ERRORS as error:
            if last_attempt:
                raise
            delay = _backoff(attempt)
            logger.warning(
                "agent.provider.retry reason=%s attempt=%s delay=%.1fs",
                type(error).__name__,
                attempt + 1,
                delay,
            )
            await asyncio.sleep(delay)
            continue
        if response.status_code not in RETRYABLE_STATUS_CODES or last_attempt:
            return response
        delay = _retry_after(response) or _backoff(attempt)
        logger.warning(
            "agent.provider.retry reason=http_%s attempt=%s delay=%.1fs",
            response.status_code,
            attempt + 1,
            delay,
        )
        await asyncio.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover - the loop always returns or raises


def _backoff(attempt: int) -> float:
    return _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]


def _retry_after(response: httpx.Response) -> float | None:
    """Honor a short Retry-After header; ignore long ones so a turn never stalls."""
    try:
        seconds = float(response.headers.get("retry-after", ""))
    except ValueError:
        return None
    return seconds if 0 < seconds <= _MAX_RETRY_AFTER_SECONDS else None


__all__ = ["RETRYABLE_STATUS_CODES", "post_with_retry", "provider_retries"]
