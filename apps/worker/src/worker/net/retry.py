"""Bounded exponential-backoff retry for transient HTTP failures. Deliberately
small and local rather than a new dependency — the policy needed here is just
"retry timeouts/5xx a few times with backoff, give up on 4xx immediately."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class NonRetryableHTTPError(Exception):
    """Raised for 4xx (other than 429) — retrying won't help, caller should skip."""

    def __init__(self, response: httpx.Response):
        self.response = response
        super().__init__(f"{response.status_code} {response.request.url}")


async def fetch_with_retry(
    fetch: Callable[[], Awaitable[httpx.Response]],
    *,
    max_retries: int,
    base_delay_seconds: float = 1.0,
) -> httpx.Response:
    attempt = 0
    while True:
        try:
            response = await fetch()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt >= max_retries:
                raise
            delay = base_delay_seconds * (2**attempt)
            logger.warning("fetch failed (%s), retrying in %.1fs", exc, delay)
            await asyncio.sleep(delay)
            attempt += 1
            continue

        if response.status_code < 400:
            return response
        if response.status_code not in RETRYABLE_STATUS_CODES:
            raise NonRetryableHTTPError(response)
        if attempt >= max_retries:
            response.raise_for_status()

        delay = base_delay_seconds * (2**attempt)
        logger.warning(
            "fetch got %s from %s, retrying in %.1fs", response.status_code, response.url, delay
        )
        await asyncio.sleep(delay)
        attempt += 1
