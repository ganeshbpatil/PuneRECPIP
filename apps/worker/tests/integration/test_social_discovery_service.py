"""SocialDiscoveryService against real Postgres and a real
LocalFilesystemObjectStorage. No network/credentials needed here — unlike
Module 5, this module never calls an external API; it only re-parses HTML
Module 4 already fetched and stored, so there's nothing to fake."""

import pytest
from corelib.enums import PageType, ScrapeJobStatus, ScrapeJobType
from corelib.models import Company, CrawlSnapshot, JobLog, ScrapeJob, SocialProfile
from corelib.storage import LocalFilesystemObjectStorage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from worker.social.service import SocialDiscoveryService

pytestmark = pytest.mark.asyncio

_HOME_HTML = """
<html><body>
<header>
  <a href="https://www.linkedin.com/company/acme-realty/">LinkedIn</a>
  <a href="https://www.facebook.com/AcmeRealtyPune">Facebook</a>
  <a href="https://www.facebook.com/sharer/sharer.php?u=https://acme.example/">Share</a>
  <a href="https://www.instagram.com/acmerealty/">Instagram</a>
  <a href="https://www.instagram.com/p/Cxyz123/">A post, not a profile</a>
  <a href="/about">About us</a>
  <a href="mailto:info@acme.example">Email</a>
</header>
</body></html>
"""

_ABOUT_HTML = """
<html><body>
<footer>
  <a href="https://www.youtube.com/channel/UC12345">YouTube</a>
  <a href="https://x.com/AcmeRealty">X</a>
  <a href="https://www.linkedin.com/company/acme-realty/">LinkedIn (again)</a>
</footer>
</body></html>
"""


async def _make_company_with_snapshots(
    session: AsyncSession, storage: LocalFilesystemObjectStorage
) -> Company:
    company = Company(name="Acme Realty Pune", slug="acme-realty-pune-social-test")
    session.add(company)
    await session.flush()

    for page_type, html in [(PageType.HOME, _HOME_HTML), (PageType.ABOUT, _ABOUT_HTML)]:
        key = f"crawls/{company.id}/{page_type.value}/raw.html"
        await storage.put(key, html.encode(), content_type="text/html")
        session.add(
            CrawlSnapshot(
                company_id=company.id,
                url=f"https://acme.example/{page_type.value}",
                page_type=page_type.value,
                raw_html_key=key,
                is_current=True,
            )
        )
    await session.flush()
    return company


async def _make_job(session: AsyncSession, company: Company) -> ScrapeJob:
    job = ScrapeJob(
        job_type=ScrapeJobType.SOCIAL_ENRICHMENT.value,
        status=ScrapeJobStatus.PENDING.value,
        company_id=company.id,
    )
    session.add(job)
    await session.commit()
    return job


async def test_discovers_and_classifies_profiles_across_snapshots(
    session: AsyncSession, tmp_path
):
    storage = LocalFilesystemObjectStorage(tmp_path)
    company = await _make_company_with_snapshots(session, storage)
    job = await _make_job(session, company)

    result = await SocialDiscoveryService(session, storage).run(job)

    assert job.status == ScrapeJobStatus.SUCCEEDED.value
    assert result["profiles_recorded"] == 5  # linkedin, facebook, instagram, youtube, x

    profiles = (
        await session.execute(select(SocialProfile).where(SocialProfile.company_id == company.id))
    ).scalars().all()
    by_platform = {p.platform: p for p in profiles}
    assert by_platform["linkedin"].url == "https://www.linkedin.com/company/acme-realty/"
    assert by_platform["linkedin"].handle == "acme-realty"
    assert by_platform["facebook"].handle == "AcmeRealtyPune"
    assert by_platform["instagram"].handle == "acmerealty"
    assert by_platform["youtube"].handle == "UC12345"
    assert by_platform["x"].handle == "AcmeRealty"

    # Non-profile links (share dialog, a post) never made it in.
    urls = {p.url for p in profiles}
    assert not any("sharer" in url for url in urls)
    assert not any("/p/Cxyz123" in url for url in urls)

    # description/follower_count/is_verified are deliberately left unset —
    # this module never visits the platforms themselves.
    for profile in profiles:
        assert profile.description is None
        assert profile.follower_count is None
        assert profile.is_verified is False

    logs = (
        await session.execute(select(JobLog).where(JobLog.scrape_job_id == job.id))
    ).scalars().all()
    assert any("social discovery complete" in log.message for log in logs)


async def test_duplicate_link_across_snapshots_is_not_duplicated(
    session: AsyncSession, tmp_path
):
    storage = LocalFilesystemObjectStorage(tmp_path)
    company = await _make_company_with_snapshots(session, storage)
    job = await _make_job(session, company)

    await SocialDiscoveryService(session, storage).run(job)

    linkedin_profiles = (
        await session.execute(
            select(SocialProfile).where(
                SocialProfile.company_id == company.id, SocialProfile.platform == "linkedin"
            )
        )
    ).scalars().all()
    # The same LinkedIn URL appears on both the home and about page.
    assert len(linkedin_profiles) == 1


async def test_rerun_upserts_without_duplicating(session: AsyncSession, tmp_path):
    storage = LocalFilesystemObjectStorage(tmp_path)
    company = await _make_company_with_snapshots(session, storage)
    job1 = await _make_job(session, company)
    await SocialDiscoveryService(session, storage).run(job1)

    job2 = await _make_job(session, company)
    result2 = await SocialDiscoveryService(session, storage).run(job2)

    assert result2["profiles_recorded"] == 5
    profiles = (
        await session.execute(select(SocialProfile).where(SocialProfile.company_id == company.id))
    ).scalars().all()
    assert len(profiles) == 5


async def test_company_with_no_crawled_content_fails_job(session: AsyncSession, tmp_path):
    storage = LocalFilesystemObjectStorage(tmp_path)
    company = Company(name="No Crawl Co", slug="no-crawl-co-social-test")
    session.add(company)
    await session.flush()
    job = await _make_job(session, company)

    with pytest.raises(ValueError, match="no crawled content"):
        await SocialDiscoveryService(session, storage).run(job)

    assert job.status == ScrapeJobStatus.FAILED.value
    assert job.error_message is not None


async def test_company_with_no_social_links_succeeds_with_zero_profiles(
    session: AsyncSession, tmp_path
):
    storage = LocalFilesystemObjectStorage(tmp_path)
    company = Company(name="No Social Co", slug="no-social-co-social-test")
    session.add(company)
    await session.flush()
    key = f"crawls/{company.id}/home/raw.html"
    await storage.put(
        key,
        b"<html><body><a href='/about'>About</a></body></html>",
        content_type="text/html",
    )
    session.add(
        CrawlSnapshot(
            company_id=company.id,
            url="https://nosocial.example/",
            page_type=PageType.HOME.value,
            raw_html_key=key,
            is_current=True,
        )
    )
    await session.flush()
    job = await _make_job(session, company)

    result = await SocialDiscoveryService(session, storage).run(job)

    assert job.status == ScrapeJobStatus.SUCCEEDED.value
    assert result["profiles_recorded"] == 0


async def test_missing_raw_html_artifact_is_skipped_not_fatal(
    session: AsyncSession, tmp_path
):
    storage = LocalFilesystemObjectStorage(tmp_path)
    company = Company(name="Missing Artifact Co", slug="missing-artifact-co-social-test")
    session.add(company)
    await session.flush()
    session.add(
        CrawlSnapshot(
            company_id=company.id,
            url="https://missing.example/",
            page_type=PageType.HOME.value,
            raw_html_key="crawls/does-not-exist/raw.html",
            is_current=True,
        )
    )
    await session.flush()
    job = await _make_job(session, company)

    result = await SocialDiscoveryService(session, storage).run(job)

    assert job.status == ScrapeJobStatus.SUCCEEDED.value
    assert result["profiles_recorded"] == 0
    logs = (
        await session.execute(select(JobLog).where(JobLog.scrape_job_id == job.id))
    ).scalars().all()
    assert any("raw html artifact missing" in log.message for log in logs)
