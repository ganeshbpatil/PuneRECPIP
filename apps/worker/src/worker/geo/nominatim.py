"""Real client for the Nominatim (OpenStreetMap) Search API — a free,
keyless, publicly documented geocoding service
(https://nominatim.org/release-docs/latest/api/Search/). This sandbox has no
network access to nominatim.openstreetmap.org (the outbound proxy allowlists
only pypi.org/npmjs.org/anthropic.com), so this is verified structurally
against `httpx.MockTransport` with realistic, documented response payloads
rather than a live call — the same honesty pattern Module 5 used for the
Claude/OpenAI SDK clients when no live credential/network access was
available, applied here to a provider that needs no credential at all, just
network reach this sandbox doesn't have.

Nominatim's usage policy
(https://operations.osmfoundation.org/policies/nominatim/) requires a
descriptive User-Agent identifying the application and caps the shared
public instance at 1 request/second — both enforced here via `worker.net`'s
shared rate limiter, the same plumbing every other outbound HTTP client in
this codebase uses. Real production volume should run against a self-hosted
Nominatim instance or a paid provider instead of the shared public one;
`base_url` is configurable for exactly that reason.
"""

import logging

import httpx

from worker.geo.provider import GeocodeResult
from worker.net.ratelimit import DomainRateLimiter
from worker.net.retry import fetch_with_retry

logger = logging.getLogger(__name__)

# Priority order for picking a "city" out of Nominatim's address breakdown.
# Which key is populated depends on the matched place's type and locale (a
# village vs. a metro area vs. an urban neighbourhood) — no single key is
# reliably present for every result, so this tries the most city-like keys
# first and falls back to broader ones.
_CITY_KEYS = ("city", "town", "municipality", "village", "suburb")


class NominatimGeocodingProvider:
    def __init__(
        self,
        client: httpx.AsyncClient,
        rate_limiter: DomainRateLimiter,
        *,
        base_url: str = "https://nominatim.openstreetmap.org/search",
        domain: str = "nominatim.openstreetmap.org",
        requests_per_second: float = 1.0,
        max_retries: int = 3,
    ):
        self._client = client
        self._rate_limiter = rate_limiter
        self._base_url = base_url
        self._domain = domain
        self._requests_per_second = requests_per_second
        self._max_retries = max_retries

    async def geocode(self, query: str) -> GeocodeResult | None:
        await self._rate_limiter.acquire(self._domain, self._requests_per_second)

        response = await fetch_with_retry(
            lambda: self._client.get(
                self._base_url,
                params={"q": query, "format": "json", "addressdetails": 1, "limit": 1},
            ),
            max_retries=self._max_retries,
        )

        results = response.json()
        if not results:
            return None
        return _parse_result(results[0])


def _parse_result(item: dict) -> GeocodeResult | None:
    try:
        latitude = float(item["lat"])
        longitude = float(item["lon"])
    except (KeyError, TypeError, ValueError):
        logger.warning("geocode result missing/invalid lat/lon: %r", item)
        return None

    address = item.get("address") or {}
    city = next((address[key] for key in _CITY_KEYS if address.get(key)), None)

    return GeocodeResult(
        latitude=latitude,
        longitude=longitude,
        display_name=item.get("display_name", ""),
        city=city,
        state=address.get("state"),
        country=address.get("country"),
        postal_code=address.get("postcode"),
        raw=item,
    )
