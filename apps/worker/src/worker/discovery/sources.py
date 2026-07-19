"""DiscoverySource implementations. `DirectoryDiscoverySource` is the one real
engine — generic paginated-HTML-directory scraping — driven entirely by a
`SiteProfile`'s CSS selectors, so a new target site is configuration, not code.
"""

import logging
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from selectolax.parser import HTMLParser, Node

from worker.discovery.models import DiscoveredListing, DiscoveryPage, SearchQuery
from worker.discovery.ratelimit import DomainRateLimiter
from worker.discovery.retry import fetch_with_retry
from worker.discovery.robots import RobotsCache
from worker.discovery.site_profiles import SiteProfile

logger = logging.getLogger(__name__)


class DiscoverySource(Protocol):
    async def search(self, query: SearchQuery, page: int) -> DiscoveryPage: ...


class RobotsDisallowedError(Exception):
    def __init__(self, url: str):
        self.url = url
        super().__init__(f"robots.txt disallows fetching {url}")


class DirectoryDiscoverySource:
    """Applies per-domain rate limiting, robots.txt compliance, and bounded
    retry-with-backoff to every request before handing the parsed page back."""

    def __init__(
        self,
        profile: SiteProfile,
        client: httpx.AsyncClient,
        rate_limiter: DomainRateLimiter,
        robots: RobotsCache,
        max_retries: int = 3,
    ):
        self._profile = profile
        self._client = client
        self._rate_limiter = rate_limiter
        self._robots = robots
        self._max_retries = max_retries

    async def search(self, query: SearchQuery, page: int) -> DiscoveryPage:
        url = self._profile.search_url_template.format(
            keyword=query.keyword, location=query.location, page=page
        )
        parts = urlsplit(url)
        path_and_query = parts.path + (f"?{parts.query}" if parts.query else "")

        if not await self._robots.is_allowed(self._profile.domain, path_and_query):
            raise RobotsDisallowedError(url)

        await self._rate_limiter.acquire(self._profile.domain, self._profile.requests_per_second)

        response = await fetch_with_retry(
            lambda: self._client.get(url), max_retries=self._max_retries
        )
        return self._parse(response.text, source_url=url)

    def _parse(self, html: str, *, source_url: str) -> DiscoveryPage:
        tree = HTMLParser(html)
        listings: list[DiscoveredListing] = []

        for card in tree.css(self._profile.result_selector):
            name_node = card.css_first(self._profile.name_selector)
            if name_node is None:
                logger.debug("skipping result card with no name at %s", source_url)
                continue

            listings.append(
                DiscoveredListing(
                    name=name_node.text(strip=True),
                    website_url=self._extract(card, self._profile.link_selector, href=True),
                    phone_raw=self._extract(card, self._profile.phone_selector),
                    snippet=self._extract(card, self._profile.snippet_selector),
                    source_listing_url=source_url,
                )
            )

        has_next = bool(
            self._profile.next_page_selector
            and tree.css_first(self._profile.next_page_selector) is not None
        )
        return DiscoveryPage(listings=listings, has_next=has_next)

    @staticmethod
    def _extract(card: Node, selector: str | None, *, href: bool = False) -> str | None:
        if not selector:
            return None
        node = card.css_first(selector)
        if node is None:
            return None
        if href:
            return node.attributes.get("href")
        return node.text(strip=True)
