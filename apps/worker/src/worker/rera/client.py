"""Generic HTTP+JSON client for a state RERA registry's public search API,
driven entirely by a RERASourceProfile (profiles.py) — one engine, config
per state, same reasoning and shared plumbing (rate limiting, robots.txt,
bounded retry) as worker.discovery.sources.DirectoryDiscoverySource.
"""

import logging
from typing import Any, Protocol

import httpx

from worker.net.ratelimit import DomainRateLimiter
from worker.net.retry import fetch_with_retry
from worker.net.robots import RobotsCache
from worker.rera.models import RERARegistryRecord
from worker.rera.profiles import RERASourceProfile

logger = logging.getLogger(__name__)


class RobotsDisallowedError(Exception):
    def __init__(self, url: str):
        self.url = url
        super().__init__(f"robots.txt disallows fetching {url}")


class RERARegistryClient(Protocol):
    async def search(self, query: str) -> list[RERARegistryRecord]: ...


class HTTPRERARegistryClient:
    def __init__(
        self,
        profile: RERASourceProfile,
        client: httpx.AsyncClient,
        rate_limiter: DomainRateLimiter,
        robots: RobotsCache,
        max_retries: int = 3,
        max_pages: int = 1,
    ):
        self._profile = profile
        self._client = client
        self._rate_limiter = rate_limiter
        self._robots = robots
        self._max_retries = max_retries
        self._max_pages = max_pages

    async def search(self, query: str) -> list[RERARegistryRecord]:
        records: list[RERARegistryRecord] = []
        for page in range(1, self._max_pages + 1):
            url = self._profile.search_url_template.format(query=query, page=page)

            if not await self._robots.is_allowed(url):
                raise RobotsDisallowedError(url)

            await self._rate_limiter.acquire(
                self._profile.domain, self._profile.requests_per_second
            )
            response = await fetch_with_retry(
                lambda url=url: self._client.get(url), max_retries=self._max_retries
            )

            items = _resolve_path(response.json(), self._profile.results_path)
            if not items:
                break

            page_records = [
                record
                for item in items
                if (record := _parse_record(item, self._profile.field_map)) is not None
            ]
            records.extend(page_records)
            if not page_records:
                break

        return records


def _resolve_path(payload: Any, path: str) -> Any:
    node = payload
    if not path:
        return node
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _parse_record(item: dict, field_map: dict[str, str]) -> RERARegistryRecord | None:
    if not isinstance(item, dict):
        return None

    values = {attr: _resolve_path(item, path) for attr, path in field_map.items()}
    registration_number = values.get("registration_number")
    registrant_name = values.get("registrant_name")
    if not registration_number or not registrant_name:
        logger.debug("skipping RERA result with no registration_number/registrant_name")
        return None

    return RERARegistryRecord(
        registration_number=str(registration_number),
        registrant_name=str(registrant_name),
        registrant_type=_optional_str(values.get("registrant_type")),
        registered_address=_optional_str(values.get("registered_address")),
        registration_date=_optional_str(values.get("registration_date")),
        expiry_date=_optional_str(values.get("expiry_date")),
        status=_optional_str(values.get("status")),
        raw=item,
    )


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)
