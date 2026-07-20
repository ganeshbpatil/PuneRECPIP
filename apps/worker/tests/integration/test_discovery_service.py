from pathlib import Path

import httpx
import pytest
from corelib.enums import ScrapeJobStatus, ScrapeJobType
from corelib.models import Company, JobLog, PhoneNumber, ScrapeJob, Website
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from worker.discovery.jobs import create_discovery_job
from worker.discovery.service import DiscoveryService
from worker.discovery.site_profiles import EXAMPLE_PROFILE
from worker.discovery.sources import DirectoryDiscoverySource
from worker.net.ratelimit import DomainRateLimiter
from worker.net.robots import RobotsCache

pytestmark = pytest.mark.asyncio

FIXTURES = Path(__file__).parent.parent / "fixtures"
PUNE_PAGE1 = (FIXTURES / "example_directory_page1.html").read_text()
PUNE_PAGE2 = (FIXTURES / "example_directory_page2.html").read_text()

MUMBAI_PAGE1 = """
<div class="results">
  <div class="listing">
    <h2 class="listing-name">Acme Realty Pune</h2>
    <a class="listing-website" href="https://acme-realty.example">Visit website</a>
    <span class="listing-phone">98765 43210</span>
    <p class="listing-snippet">Also serving Mumbai clients.</p>
  </div>
  <div class="listing">
    <h2 class="listing-name">Mumbai Realty Experts</h2>
    <span class="listing-phone">99887 66554</span>
    <p class="listing-snippet">No website listed.</p>
  </div>
</div>
"""

SERVER_ERROR_PAGE_QUERY = ("broker", "nagpur")


def _make_transport(call_log: list[tuple[str, str, str]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")

        keyword = request.url.params.get("q")
        location = request.url.params.get("loc")
        page = request.url.params.get("page")
        call_log.append((keyword, location, page))

        if (keyword, location) == SERVER_ERROR_PAGE_QUERY:
            return httpx.Response(500, text="server error")
        if keyword == "broker" and location == "pune":
            return httpx.Response(200, text=PUNE_PAGE1 if page == "1" else PUNE_PAGE2)
        if keyword == "broker" and location == "mumbai" and page == "1":
            return httpx.Response(200, text=MUMBAI_PAGE1)
        return httpx.Response(404, text="not found")

    return httpx.MockTransport(handler)


def _make_service(session: AsyncSession, call_log: list[tuple[str, str, str]]) -> DiscoveryService:
    client = httpx.AsyncClient(transport=_make_transport(call_log))
    source = DirectoryDiscoverySource(
        profile=EXAMPLE_PROFILE,
        client=client,
        rate_limiter=DomainRateLimiter(default_requests_per_second=1000),
        robots=RobotsCache(client, user_agent="TestBot"),
        max_retries=1,
    )
    return DiscoveryService(session, source)


async def _make_job(session: AsyncSession, locations: list[str]) -> ScrapeJob:
    return await create_discovery_job(
        session, keywords=["broker"], locations=locations, site_profile="example_directory"
    )


async def test_create_discovery_job_persists_expected_payload(session: AsyncSession):
    job = await _make_job(session, ["pune"])

    assert job.job_type == ScrapeJobType.DISCOVERY.value
    assert job.status == ScrapeJobStatus.PENDING.value
    assert job.payload == {
        "keywords": ["broker"],
        "locations": ["pune"],
        "site_profile": "example_directory",
        "max_pages_per_query": 20,
    }


async def test_full_run_discovers_paginates_dedupes_and_logs(session: AsyncSession):
    job = await _make_job(session, ["pune", "mumbai"])
    call_log: list[tuple[str, str, str]] = []

    result = await _make_service(session, call_log).run(job)

    assert result.queries_run == 2
    assert result.companies_discovered == 4  # Acme, Pune Prime, Baner Broker, Mumbai Realty
    assert result.companies_skipped_duplicate == 1  # Acme re-seen under "mumbai"
    assert result.errors == []
    assert job.status == ScrapeJobStatus.SUCCEEDED.value
    assert job.checkpoint == {"query_index": 2, "next_page": 1}

    companies = (await session.execute(select(Company.name))).scalars().all()
    assert set(companies) == {
        "Acme Realty Pune",
        "Pune Prime Properties",
        "Baner Broker Associates",
        "Mumbai Realty Experts",
    }

    websites = (await session.execute(select(Website.domain))).scalars().all()
    assert set(websites) == {"acme-realty.example", "puneprime.example", "banerbroker.example"}

    phones = (await session.execute(select(PhoneNumber.phone_number))).scalars().all()
    assert "+919876543210" in phones  # Acme's phone, normalized, saved once (first sighting)

    pending_crawl_jobs = (
        await session.execute(
            select(ScrapeJob).where(ScrapeJob.job_type == ScrapeJobType.CRAWL.value)
        )
    ).scalars().all()
    assert len(pending_crawl_jobs) == 4
    assert {j.status for j in pending_crawl_jobs} == {ScrapeJobStatus.PENDING.value}

    logs = (
        await session.execute(select(JobLog).where(JobLog.scrape_job_id == job.id))
    ).scalars().all()
    assert sum(1 for log in logs if "discovered company" in log.message) == 4
    assert sum(1 for log in logs if "skipped duplicate" in log.message) == 1


async def test_resume_does_not_refetch_completed_queries(session: AsyncSession):
    job = await _make_job(session, ["pune", "mumbai"])

    # Simulate the "pune" query having already completed in a prior (crashed)
    # run: its companies (and, per _save_listing's atomic insert, their
    # websites) already exist in the DB, and the job's checkpoint / result
    # reflect that the run is positioned at the start of "mumbai".
    acme = Company(name="Acme Realty Pune", slug="acme-realty-pune")
    session.add_all(
        [
            acme,
            Company(name="Pune Prime Properties", slug="pune-prime-properties"),
            Company(name="Baner Broker Associates", slug="baner-broker-associates"),
        ]
    )
    await session.flush()
    session.add(
        Website(company_id=acme.id, url="https://acme-realty.example", domain="acme-realty.example")
    )
    await session.flush()
    job.checkpoint = {"query_index": 1, "next_page": 1}
    job.result = {
        "companies_discovered": 3,
        "companies_skipped_duplicate": 0,
        "queries_run": 1,
        "errors": [],
    }
    await session.commit()

    call_log: list[tuple[str, str, str]] = []
    result = await _make_service(session, call_log).run(job)

    assert ("broker", "pune", "1") not in call_log
    assert ("broker", "pune", "2") not in call_log
    assert ("broker", "mumbai", "1") in call_log

    assert result.companies_discovered == 4  # 3 carried over + Mumbai Realty Experts
    assert result.companies_skipped_duplicate == 1  # Acme Realty Pune, by domain
    assert result.queries_run == 2


async def test_per_query_http_failure_is_recorded_not_fatal(session: AsyncSession):
    job = await create_discovery_job(
        session, keywords=["broker"], locations=["pune", "nagpur"], site_profile="example_directory"
    )
    call_log: list[tuple[str, str, str]] = []

    result = await _make_service(session, call_log).run(job)

    assert job.status == ScrapeJobStatus.SUCCEEDED.value  # one bad query doesn't fail the job
    assert len(result.errors) == 1
    assert "nagpur" in result.errors[0]
    assert result.companies_discovered == 3  # pune's 3 listings still saved


async def test_job_level_failure_marks_job_failed(session: AsyncSession):
    job = ScrapeJob(
        job_type=ScrapeJobType.DISCOVERY.value,
        status=ScrapeJobStatus.PENDING.value,
        payload={"locations": ["pune"]},  # missing "keywords" -> KeyError inside run()
    )
    session.add(job)
    await session.commit()

    call_log: list[tuple[str, str, str]] = []
    with pytest.raises(KeyError):
        await _make_service(session, call_log).run(job)

    assert job.status == ScrapeJobStatus.FAILED.value
    assert job.error_message is not None
