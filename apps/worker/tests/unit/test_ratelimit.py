import time

import pytest
from worker.discovery.ratelimit import DomainRateLimiter, TokenBucket


@pytest.mark.asyncio
async def test_token_bucket_allows_burst_up_to_capacity():
    bucket = TokenBucket(requests_per_second=10, burst=3)
    start = time.monotonic()
    for _ in range(3):
        await bucket.acquire()
    # First `burst` acquisitions should be effectively instant.
    assert time.monotonic() - start < 0.05


@pytest.mark.asyncio
async def test_token_bucket_throttles_beyond_capacity():
    bucket = TokenBucket(requests_per_second=20, burst=1)
    start = time.monotonic()
    await bucket.acquire()
    await bucket.acquire()  # bucket empty -> must wait ~1/20s
    assert time.monotonic() - start >= 0.04


@pytest.mark.asyncio
async def test_domain_rate_limiter_uses_separate_buckets_per_domain():
    limiter = DomainRateLimiter(default_requests_per_second=1000)
    start = time.monotonic()
    await limiter.acquire("a.example")
    await limiter.acquire("b.example")
    # Different domains never contend for the same bucket.
    assert time.monotonic() - start < 0.05


def test_token_bucket_rejects_non_positive_rate():
    with pytest.raises(ValueError):
        TokenBucket(requests_per_second=0)
