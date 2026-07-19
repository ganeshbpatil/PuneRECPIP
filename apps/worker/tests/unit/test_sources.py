from pathlib import Path

import httpx
import pytest
from worker.discovery.models import SearchQuery
from worker.discovery.site_profiles import EXAMPLE_PROFILE
from worker.discovery.sources import DirectoryDiscoverySource, RobotsDisallowedError
from worker.net.ratelimit import DomainRateLimiter
from worker.net.robots import RobotsCache

pytestmark = pytest.mark.asyncio

FIXTURES = Path(__file__).parent.parent / "fixtures"
PAGE_1 = (FIXTURES / "example_directory_page1.html").read_text()
PAGE_2 = (FIXTURES / "example_directory_page2.html").read_text()


def _fixture_transport(*, robots_allow: bool = True) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            body = "User-agent: *\nAllow: /\n" if robots_allow else "User-agent: *\nDisallow: /\n"
            return httpx.Response(200, text=body)
        if request.url.params.get("page") == "2":
            return httpx.Response(200, text=PAGE_2)
        return httpx.Response(200, text=PAGE_1)

    return httpx.MockTransport(handler)


async def _make_source(*, robots_allow: bool = True) -> DirectoryDiscoverySource:
    client = httpx.AsyncClient(transport=_fixture_transport(robots_allow=robots_allow))
    return DirectoryDiscoverySource(
        profile=EXAMPLE_PROFILE,
        client=client,
        rate_limiter=DomainRateLimiter(default_requests_per_second=1000),
        robots=RobotsCache(client, user_agent="TestBot"),
    )


async def test_parses_listings_and_detects_next_page():
    source = await _make_source()
    page = await source.search(SearchQuery(keyword="broker", location="pune"), page=1)

    assert page.has_next is True
    assert [listing.name for listing in page.listings] == [
        "Acme Realty Pune",
        "Pune Prime Properties",
    ]
    first = page.listings[0]
    assert first.website_url == "https://acme-realty.example"
    assert first.phone_raw == "020-2567-8901"
    assert "Kothrud" in first.snippet


async def test_last_page_has_no_next():
    source = await _make_source()
    page = await source.search(SearchQuery(keyword="broker", location="pune"), page=2)

    assert page.has_next is False
    assert len(page.listings) == 1
    assert page.listings[0].name == "Baner Broker Associates"


async def test_robots_disallow_raises():
    source = await _make_source(robots_allow=False)
    with pytest.raises(RobotsDisallowedError):
        await source.search(SearchQuery(keyword="broker", location="pune"), page=1)
