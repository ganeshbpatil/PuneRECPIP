"""GeoIntelligenceService against real Postgres/PostGIS — storing and
reading back a real Geography point is exactly the database feature worth
exercising for real, same rationale as every other module's *-matching
integration test. The geocoding provider is the one faked dependency (this
sandbox has no network access to Nominatim or any geocoding provider — see
worker/geo/nominatim.py); FakeGeocodingProvider stands in for it, mirroring
FakeAIExtractor (Module 5) / FakeRERARegistryClient (Module 7).
"""

import pytest
from corelib.enums import ScrapeJobStatus, ScrapeJobType
from corelib.models import Address, Company, JobLog, ScrapeJob, ServiceArea
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from worker.geo.provider import GeocodeResult
from worker.geo.service import GeoIntelligenceService

pytestmark = pytest.mark.asyncio


class FakeGeocodingProvider:
    def __init__(self, results: dict[str, GeocodeResult]):
        self._results = results
        self.queries: list[str] = []

    async def geocode(self, query: str) -> GeocodeResult | None:
        self.queries.append(query)
        return self._results.get(query)


KOTHRUD = GeocodeResult(
    latitude=18.5074,
    longitude=73.8077,
    display_name="Kothrud, Pune, Maharashtra, India",
    city="Pune",
    state="Maharashtra",
    country="India",
    postal_code="411038",
)
BANER = GeocodeResult(
    latitude=18.5590,
    longitude=73.7868,
    display_name="Baner, Pune, Maharashtra, India",
    city="Pune",
    state="Maharashtra",
    postal_code="411045",
)


async def _make_company(session: AsyncSession, name: str, slug: str) -> Company:
    company = Company(name=name, slug=slug)
    session.add(company)
    await session.flush()
    return company


async def _make_job(session: AsyncSession, company: Company) -> ScrapeJob:
    job = ScrapeJob(
        job_type=ScrapeJobType.GEO_RESOLUTION.value,
        status=ScrapeJobStatus.PENDING.value,
        company_id=company.id,
    )
    session.add(job)
    await session.commit()
    return job


async def _point(session: AsyncSession, geom) -> tuple[float, float]:
    """Returns (longitude, latitude) parsed from a real ST_AsText(geom) call
    against Postgres — proves the value stored is a genuine, queryable
    PostGIS geography, not just an opaque blob."""
    wkt = (await session.execute(select(func.ST_AsText(geom)))).scalar_one()
    lon, lat = wkt.removeprefix("POINT(").removesuffix(")").split()
    return float(lon), float(lat)


async def test_geocodes_address_missing_geom(session: AsyncSession):
    company = await _make_company(session, "Kothrud Realty", "kothrud-realty-geo-test")
    address = Address(company_id=company.id, locality="Kothrud", country="India")
    session.add(address)
    await session.flush()
    job = await _make_job(session, company)
    provider = FakeGeocodingProvider({"Kothrud, India": KOTHRUD})

    result = await GeoIntelligenceService(session, provider).run(job)

    assert job.status == ScrapeJobStatus.SUCCEEDED.value
    assert result == {"addresses_geocoded": 1, "service_areas_resolved": 0}

    await session.refresh(address)
    assert address.city == "Pune"
    assert address.state == "Maharashtra"
    assert address.postal_code == "411038"
    assert float(address.latitude) == pytest.approx(18.5074)
    assert float(address.longitude) == pytest.approx(73.8077)
    lon, lat = await _point(session, address.geom)
    assert lon == pytest.approx(73.8077)
    assert lat == pytest.approx(18.5074)


async def test_existing_city_state_not_overwritten(session: AsyncSession):
    company = await _make_company(session, "Preset Realty", "preset-realty-geo-test")
    address = Address(
        company_id=company.id,
        locality="Kothrud",
        city="Existing City",
        state="Existing State",
        country="India",
    )
    session.add(address)
    await session.flush()
    job = await _make_job(session, company)
    provider = FakeGeocodingProvider({"Kothrud, Existing City, Existing State, India": KOTHRUD})

    await GeoIntelligenceService(session, provider).run(job)

    await session.refresh(address)
    assert address.city == "Existing City"
    assert address.state == "Existing State"


async def test_service_area_resolves_using_company_known_city(session: AsyncSession):
    company = await _make_company(session, "Baner Realty", "baner-realty-geo-test")
    session.add(
        Address(company_id=company.id, city="Pune", state="Maharashtra", is_primary=True)
    )
    area = ServiceArea(company_id=company.id, locality="Baner")
    session.add(area)
    await session.flush()
    job = await _make_job(session, company)
    provider = FakeGeocodingProvider({"Baner, Pune, Maharashtra, India": BANER})

    result = await GeoIntelligenceService(session, provider).run(job)

    assert result["service_areas_resolved"] == 1
    await session.refresh(area)
    assert area.city == "Pune"
    lon, lat = await _point(session, area.geom)
    assert lon == pytest.approx(73.7868)
    assert lat == pytest.approx(18.5590)


async def test_service_area_falls_back_to_pune_default_with_no_company_context(
    session: AsyncSession,
):
    company = await _make_company(session, "No Context Realty", "no-context-realty-geo-test")
    area = ServiceArea(company_id=company.id, locality="Baner")
    session.add(area)
    await session.flush()
    job = await _make_job(session, company)
    provider = FakeGeocodingProvider({"Baner, Pune, Maharashtra, India": BANER})

    result = await GeoIntelligenceService(session, provider).run(job)

    assert result["service_areas_resolved"] == 1
    assert provider.queries == ["Baner, Pune, Maharashtra, India"]


async def test_no_geocode_match_is_skipped_not_fatal(session: AsyncSession):
    company = await _make_company(session, "Unmatchable Co", "unmatchable-co-geo-test")
    session.add(Address(company_id=company.id, locality="Nowhere Place", country="India"))
    await session.flush()
    job = await _make_job(session, company)
    provider = FakeGeocodingProvider({})  # empty -> always None

    result = await GeoIntelligenceService(session, provider).run(job)

    assert job.status == ScrapeJobStatus.SUCCEEDED.value
    assert result == {"addresses_geocoded": 0, "service_areas_resolved": 0}

    logs = (
        await session.execute(select(JobLog).where(JobLog.scrape_job_id == job.id))
    ).scalars().all()
    assert any("no geocode match for address" in log.message for log in logs)


async def test_already_geocoded_address_is_not_reprocessed(session: AsyncSession):
    company = await _make_company(session, "Already Geocoded Co", "already-geocoded-geo-test")
    address = Address(company_id=company.id, locality="Kothrud", country="India")
    session.add(address)
    await session.flush()
    job1 = await _make_job(session, company)
    provider = FakeGeocodingProvider({"Kothrud, India": KOTHRUD})
    await GeoIntelligenceService(session, provider).run(job1)

    job2 = await _make_job(session, company)
    result2 = await GeoIntelligenceService(session, provider).run(job2)

    assert result2 == {"addresses_geocoded": 0, "service_areas_resolved": 0}
    assert provider.queries == ["Kothrud, India"]  # only called once, on the first job


async def test_company_with_no_location_data_succeeds_with_zero_work(
    session: AsyncSession,
):
    company = await _make_company(session, "No Location Data Co", "no-location-data-geo-test")
    job = await _make_job(session, company)
    provider = FakeGeocodingProvider({})

    result = await GeoIntelligenceService(session, provider).run(job)

    assert job.status == ScrapeJobStatus.SUCCEEDED.value
    assert result == {"addresses_geocoded": 0, "service_areas_resolved": 0}
