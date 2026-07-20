import httpx
import pytest
from worker.net.ratelimit import DomainRateLimiter
from worker.net.robots import RobotsCache
from worker.rera.client import HTTPRERARegistryClient, RobotsDisallowedError
from worker.rera.profiles import EXAMPLE_PROFILE

pytestmark = pytest.mark.asyncio

PAGE_1 = {
    "data": {
        "results": [
            {
                "registrationNo": "P52100012345",
                "applicantName": "Acme Realty Pune",
                "category": "Agent",
                "address": "FC Road, Pune",
                "regDate": "2019-04-01",
                "validTill": "2024-03-31",
                "status": "Active",
            },
            {
                "registrationNo": "P52100067890",
                "applicantName": "Baner Broker Associates",
                "category": "Promoter",
                "address": "Baner, Pune",
                "regDate": "01-06-2020",
                "validTill": "31-05-2025",
                "status": "Expired",
            },
            # Missing the required registrant name -> should be skipped, not
            # raise or crash the whole page.
            {"registrationNo": "P52100099999", "category": "Agent"},
        ]
    }
}
PAGE_2 = {"data": {"results": []}}


def _fixture_transport(*, robots_allow: bool = True) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            body = "User-agent: *\nAllow: /\n" if robots_allow else "User-agent: *\nDisallow: /\n"
            return httpx.Response(200, text=body)
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=PAGE_2)
        return httpx.Response(200, json=PAGE_1)

    return httpx.MockTransport(handler)


def _make_client(*, robots_allow: bool = True, max_pages: int = 1) -> HTTPRERARegistryClient:
    http_client = httpx.AsyncClient(transport=_fixture_transport(robots_allow=robots_allow))
    return HTTPRERARegistryClient(
        profile=EXAMPLE_PROFILE,
        client=http_client,
        rate_limiter=DomainRateLimiter(default_requests_per_second=1000),
        robots=RobotsCache(http_client, user_agent="TestBot"),
        max_pages=max_pages,
    )


async def test_parses_records_and_maps_fields():
    client = _make_client()
    records = await client.search("Acme")

    assert len(records) == 2  # the malformed third entry is skipped
    first = records[0]
    assert first.registration_number == "P52100012345"
    assert first.registrant_name == "Acme Realty Pune"
    assert first.registrant_type == "Agent"
    assert first.registered_address == "FC Road, Pune"
    assert first.registration_date == "2019-04-01"
    assert first.expiry_date == "2024-03-31"
    assert first.status == "Active"
    assert first.raw["registrationNo"] == "P52100012345"


async def test_second_record_mapped_independently():
    client = _make_client()
    records = await client.search("Baner")

    second = records[1]
    assert second.registration_number == "P52100067890"
    assert second.registrant_name == "Baner Broker Associates"
    assert second.status == "Expired"


async def test_empty_next_page_stops_pagination():
    client = _make_client(max_pages=2)
    records = await client.search("Acme")

    assert len(records) == 2  # page 2 returned no results, so nothing added


async def test_robots_disallow_raises():
    client = _make_client(robots_allow=False)
    with pytest.raises(RobotsDisallowedError):
        await client.search("Acme")
