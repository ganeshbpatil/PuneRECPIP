"""Integration tests for CrawlService against real infrastructure: real
Postgres (see conftest.py), a real local HTTP server serving the fixture site
in tests/fixtures/site/ (plain http.server — not proxied, so it works in this
sandbox unlike a live third-party site would), a real Chromium browser via
BrowserPool, and a real LocalFilesystemObjectStorage writing to tmp_path.
Nothing here is mocked except the object storage backend choice itself (local
vs S3 is a config swap, not a behavior difference — see corelib/test_storage.py
for the S3-compatible path, verified separately via moto).
"""

import http.server
import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from corelib.enums import CompanyStatus, ScrapeJobStatus, ScrapeJobType, WebsiteStatus
from corelib.models import (
    Company,
    CrawlSnapshot,
    EmailAddress,
    JobLog,
    PhoneNumber,
    ScrapeJob,
    Website,
)
from corelib.storage import LocalFilesystemObjectStorage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from worker.crawling.browser import BrowserPool
from worker.crawling.service import CrawlService
from worker.net.ratelimit import DomainRateLimiter
from worker.net.robots import RobotsCache

pytestmark = pytest.mark.asyncio

FIXTURE_SITE_DIR = Path(__file__).parent.parent / "fixtures" / "site"


def _make_handler(directory: str, hit_counts: dict[str, int]) -> type:
    class _CountingHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass  # silence default request logging to stderr

        def do_GET(self) -> None:  # noqa: N802 - http.server's naming convention
            hit_counts[self.path] = hit_counts.get(self.path, 0) + 1
            super().do_GET()

    return _CountingHandler


@pytest.fixture
def fixture_site():
    hit_counts: dict[str, int] = {}
    handler_cls = _make_handler(str(FIXTURE_SITE_DIR), hit_counts)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(base_url=f"http://127.0.0.1:{port}", hit_counts=hit_counts)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture
async def browser(chromium_executable_path: str | None):
    async with BrowserPool(
        executable_path=chromium_executable_path,
        max_concurrent_pages=3,
        user_agent="PuneRECPIPTestBot/0.1",
        page_timeout_seconds=10,
    ) as pool:
        yield pool


@pytest.fixture
def object_storage(tmp_path):
    return LocalFilesystemObjectStorage(tmp_path)


async def _make_service(
    browser: BrowserPool, object_storage, session: AsyncSession
) -> CrawlService:
    robots_client = httpx.AsyncClient()
    return CrawlService(
        session,
        browser,
        object_storage,
        rate_limiter=DomainRateLimiter(default_requests_per_second=1000),
        robots=RobotsCache(robots_client, user_agent="PuneRECPIPTestBot/0.1"),
        max_pages_per_company=6,
    )


async def _make_company_with_website(
    session: AsyncSession, base_url: str
) -> tuple[Company, Website]:
    company = Company(name="Acme Realty Pune", slug="acme-realty-pune-crawl-test")
    session.add(company)
    await session.flush()
    website = Website(
        company_id=company.id,
        url=f"{base_url}/index.html",
        domain="127.0.0.1",
        is_primary=True,
    )
    session.add(website)
    await session.flush()
    return company, website


async def test_full_crawl_persists_snapshots_contacts_and_hands_off(
    session: AsyncSession, browser: BrowserPool, object_storage, fixture_site
):
    company, website = await _make_company_with_website(session, fixture_site.base_url)
    job = ScrapeJob(
        job_type=ScrapeJobType.CRAWL.value,
        status=ScrapeJobStatus.PENDING.value,
        company_id=company.id,
    )
    session.add(job)
    await session.commit()

    result = await (await _make_service(browser, object_storage, session)).run(job)

    assert job.status == ScrapeJobStatus.SUCCEEDED.value
    assert result.pages_crawled == 4  # home + about + services + contact
    assert result.errors == []

    snapshots = (
        await session.execute(select(CrawlSnapshot).where(CrawlSnapshot.company_id == company.id))
    ).scalars().all()
    assert {s.page_type for s in snapshots} == {"home", "about", "services", "contact"}
    assert all(s.is_current for s in snapshots)
    assert all(
        s.raw_html_key and s.clean_html_key and s.markdown_key and s.screenshot_key
        for s in snapshots
    )
    for s in snapshots:
        assert await object_storage.exists(s.raw_html_key)
        assert await object_storage.exists(s.screenshot_key)

    emails = (
        await session.execute(
            select(EmailAddress.email).where(EmailAddress.company_id == company.id)
        )
    ).scalars().all()
    assert "sales@acme-realty.example" in emails

    phones = (
        await session.execute(
            select(PhoneNumber.phone_number).where(PhoneNumber.company_id == company.id)
        )
    ).scalars().all()
    assert "+919876543210" in phones

    await session.refresh(company)
    await session.refresh(website)
    assert company.status == CompanyStatus.CRAWLED.value
    assert company.last_crawled_at is not None
    assert website.status == WebsiteStatus.ACTIVE.value

    extraction_jobs = (
        await session.execute(
            select(ScrapeJob).where(
                ScrapeJob.job_type == ScrapeJobType.EXTRACTION.value,
                ScrapeJob.company_id == company.id,
            )
        )
    ).scalars().all()
    assert len(extraction_jobs) == 1
    assert extraction_jobs[0].status == ScrapeJobStatus.PENDING.value

    logs = (
        await session.execute(select(JobLog).where(JobLog.scrape_job_id == job.id))
    ).scalars().all()
    assert sum(1 for log in logs if "crawled page" in log.message) == 4


async def test_resume_does_not_refetch_already_visited_pages(
    session: AsyncSession, browser: BrowserPool, object_storage, fixture_site
):
    company, website = await _make_company_with_website(session, fixture_site.base_url)
    job = ScrapeJob(
        job_type=ScrapeJobType.CRAWL.value,
        status=ScrapeJobStatus.PENDING.value,
        company_id=company.id,
    )
    session.add(job)
    await session.commit()

    # First run crawls everything.
    await (await _make_service(browser, object_storage, session)).run(job)
    assert fixture_site.hit_counts.get("/about.html") == 1

    # Reset the job to pending (as if it needs to run again) but keep its
    # checkpoint — this is exactly the state a crashed-and-restarted task
    # would see: checkpoint intact, status not yet finalized.
    job.status = ScrapeJobStatus.PENDING.value
    await session.commit()

    result = await (await _make_service(browser, object_storage, session)).run(job)

    # pages_crawled carries forward across resumed runs (same accumulating-
    # count design as DiscoveryRunResult) — unchanged from run 1 confirms
    # nothing new was crawled, not that the counter was reset to 0.
    assert result.pages_crawled == 4
    # The real proof resume worked: every page's hit count is still exactly 1
    # after *two* service.run() calls — nothing was fetched a second time.
    assert fixture_site.hit_counts.get("/about.html") == 1
    assert fixture_site.hit_counts.get("/index.html") == 1
    assert fixture_site.hit_counts.get("/services.html") == 1
    assert fixture_site.hit_counts.get("/contact.html") == 1


async def test_missing_website_fails_job(
    session: AsyncSession, browser: BrowserPool, object_storage
):
    company = Company(name="No Website Co", slug="no-website-co-crawl-test")
    session.add(company)
    await session.flush()
    job = ScrapeJob(
        job_type=ScrapeJobType.CRAWL.value,
        status=ScrapeJobStatus.PENDING.value,
        company_id=company.id,
    )
    session.add(job)
    await session.commit()

    with pytest.raises(ValueError, match="no website"):
        await (await _make_service(browser, object_storage, session)).run(job)

    assert job.status == ScrapeJobStatus.FAILED.value
    assert job.error_message is not None


async def test_unreachable_candidate_page_is_recorded_not_fatal(
    session: AsyncSession, browser: BrowserPool, object_storage, fixture_site
):
    company, website = await _make_company_with_website(session, fixture_site.base_url)
    job = ScrapeJob(
        job_type=ScrapeJobType.CRAWL.value,
        status=ScrapeJobStatus.PENDING.value,
        company_id=company.id,
        # Pre-seed the checkpoint past the homepage step, with one candidate
        # page pointing at a port nothing listens on (connection refused) —
        # simulates a homepage nav link to a genuinely broken internal page.
        checkpoint={
            "visited": [f"{fixture_site.base_url}/index.html"],
            "candidate_pages": [
                {"url": "http://127.0.0.1:1/broken.html", "page_type": "about"},
                {"url": f"{fixture_site.base_url}/contact.html", "page_type": "contact"},
            ],
        },
    )
    session.add(job)
    await session.commit()

    result = await (await _make_service(browser, object_storage, session)).run(job)

    assert job.status == ScrapeJobStatus.SUCCEEDED.value  # one bad page doesn't fail the job
    assert result.pages_crawled == 1  # only contact.html succeeded
    assert len(result.errors) == 1
    assert "127.0.0.1:1" in result.errors[0]
