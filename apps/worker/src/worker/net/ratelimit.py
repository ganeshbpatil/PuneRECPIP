"""Per-domain async token-bucket rate limiter. One bucket per domain (not one
global bucket) so discovery running across several directories at once doesn't
let a fast, permissive site's budget get eaten by a slow, strict one."""

import asyncio
import time


class TokenBucket:
    def __init__(self, requests_per_second: float, burst: int | None = None):
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self.rate = requests_per_second
        self.capacity = burst or max(1, int(requests_per_second))
        self._tokens = float(self.capacity)
        self._updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._updated_at
                self._updated_at = now
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await asyncio.sleep((1 - self._tokens) / self.rate)


class DomainRateLimiter:
    """Lazily creates one `TokenBucket` per domain the first time it's seen."""

    def __init__(self, default_requests_per_second: float):
        self._default_rate = default_requests_per_second
        self._buckets: dict[str, TokenBucket] = {}

    def _bucket_for(self, domain: str, requests_per_second: float | None) -> TokenBucket:
        if domain not in self._buckets:
            self._buckets[domain] = TokenBucket(requests_per_second or self._default_rate)
        return self._buckets[domain]

    async def acquire(self, domain: str, requests_per_second: float | None = None) -> None:
        await self._bucket_for(domain, requests_per_second).acquire()
