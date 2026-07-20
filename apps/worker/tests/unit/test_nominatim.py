import httpx
import pytest
from worker.geo.nominatim import NominatimGeocodingProvider
from worker.net.ratelimit import DomainRateLimiter

pytestmark = pytest.mark.asyncio

KOTHRUD_RESULT = [
    {
        "place_id": 12345,
        "osm_type": "relation",
        "osm_id": 654321,
        "lat": "18.5074",
        "lon": "73.8077",
        "display_name": "Kothrud, Pune, Pune District, Maharashtra, 411038, India",
        "address": {
            "suburb": "Kothrud",
            "city": "Pune",
            "state_district": "Pune District",
            "state": "Maharashtra",
            "postcode": "411038",
            "country": "India",
            "country_code": "in",
        },
        "boundingbox": ["18.49", "18.52", "73.79", "73.82"],
    }
]

# A small town result, where Nominatim's address dict uses "town" instead of
# "city" — the exact ambiguity _CITY_KEYS exists to handle.
TOWN_RESULT = [
    {
        "lat": "18.6298",
        "lon": "73.8010",
        "display_name": "Chakan, Pune District, Maharashtra, 410501, India",
        "address": {
            "town": "Chakan",
            "state": "Maharashtra",
            "postcode": "410501",
            "country": "India",
        },
    }
]


def _transport(payload) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


def _make_provider(payload) -> NominatimGeocodingProvider:
    client = httpx.AsyncClient(transport=_transport(payload))
    return NominatimGeocodingProvider(
        client, DomainRateLimiter(default_requests_per_second=1000)
    )


async def test_parses_result_with_city_key():
    provider = _make_provider(KOTHRUD_RESULT)
    result = await provider.geocode("Kothrud, Pune, Maharashtra, India")

    assert result is not None
    assert result.latitude == pytest.approx(18.5074)
    assert result.longitude == pytest.approx(73.8077)
    assert result.city == "Pune"
    assert result.state == "Maharashtra"
    assert result.country == "India"
    assert result.postal_code == "411038"
    assert result.display_name.startswith("Kothrud, Pune")
    assert result.raw["place_id"] == 12345


async def test_falls_back_to_town_key_when_city_absent():
    provider = _make_provider(TOWN_RESULT)
    result = await provider.geocode("Chakan, Pune, Maharashtra, India")

    assert result is not None
    assert result.city == "Chakan"


async def test_empty_results_returns_none():
    provider = _make_provider([])
    result = await provider.geocode("Nonexistent Place XYZ")

    assert result is None


async def test_malformed_lat_lon_returns_none():
    provider = _make_provider([{"lat": "not-a-number", "lon": "73.8", "address": {}}])
    result = await provider.geocode("Bad Data Place")

    assert result is None
