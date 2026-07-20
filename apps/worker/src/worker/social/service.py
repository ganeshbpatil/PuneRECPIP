"""Social profile discovery (Module 6): scans a company's own already-crawled
pages (Module 4's `CrawlSnapshot` rows) for outbound links to LinkedIn,
Facebook, Instagram, YouTube, or X, and records the ones that classify as an
actual profile/channel/company page rather than a post/video/share link.

Deliberately does not visit LinkedIn/Facebook/Instagram/YouTube/X — only a
company's own site is read, and only links the company already published
there. That means the `description`, `follower_count`, and `is_verified`
columns on `SocialProfile` are left unset by this module; populating them
would require fetching the platform page itself, which for LinkedIn,
Facebook, and Instagram would violate their terms of service (automated
access to profile/search pages). See docs/modules/06-social-discovery.md.
"""

import logging
from datetime import UTC, datetime
from urllib.parse import urljoin

from corelib.enums import LogLevel, ScrapeJobStatus
from corelib.models import Company, CrawlSnapshot, JobLog, ScrapeJob, SocialProfile
from corelib.storage import ObjectNotFoundError, ObjectStorage
from selectolax.parser import HTMLParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from worker.social.link_classification import SocialLinkMatch, classify_social_link

logger = logging.getLogger(__name__)

_SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "#")


class SocialDiscoveryService:
    def __init__(self, session: AsyncSession, storage: ObjectStorage):
        self._session = session
        self._storage = storage

    async def run(self, job: ScrapeJob) -> dict:
        job.status = ScrapeJobStatus.RUNNING.value
        if job.started_at is None:
            job.started_at = datetime.now(UTC)
        await self._session.commit()

        profiles_recorded = 0
        try:
            company = await self._load_company(job)
            snapshots = await self._load_snapshots(company)
            if not snapshots:
                raise ValueError(
                    f"company {company.id} has no crawled content to discover "
                    "social profiles from"
                )

            matches: dict[str, SocialLinkMatch] = {}
            for snapshot in snapshots:
                if not snapshot.raw_html_key:
                    continue
                try:
                    raw = await self._storage.get(snapshot.raw_html_key)
                except ObjectNotFoundError:
                    await self._log(
                        job,
                        LogLevel.WARNING,
                        "raw html artifact missing for snapshot",
                        {"snapshot_id": str(snapshot.id)},
                    )
                    continue
                html = raw.decode("utf-8", errors="replace")
                for href in self._extract_hrefs(html, snapshot.url):
                    match = classify_social_link(href)
                    if match is not None and match.url not in matches:
                        matches[match.url] = match

            for match in matches.values():
                await self._upsert_profile(company, match)
                profiles_recorded += 1

            await self._log(
                job,
                LogLevel.INFO,
                "social discovery complete",
                {"profiles_recorded": profiles_recorded},
            )
            job.status = ScrapeJobStatus.SUCCEEDED.value
        except Exception as exc:  # noqa: BLE001 - persist failure state before re-raising
            job.status = ScrapeJobStatus.FAILED.value
            job.error_message = str(exc)
            await self._log(
                job, LogLevel.ERROR, "social discovery job failed", {"error": str(exc)}
            )
            job.finished_at = datetime.now(UTC)
            await self._session.commit()
            raise
        else:
            job.result = {"profiles_recorded": profiles_recorded}
            job.finished_at = datetime.now(UTC)
            await self._session.commit()

        return {"profiles_recorded": profiles_recorded}

    async def _load_company(self, job: ScrapeJob) -> Company:
        if job.company_id is None:
            raise ValueError("social discovery jobs must have company_id set")
        company = (
            await self._session.execute(select(Company).where(Company.id == job.company_id))
        ).scalar_one_or_none()
        if company is None:
            raise ValueError(f"company {job.company_id} not found")
        return company

    async def _load_snapshots(self, company: Company) -> list[CrawlSnapshot]:
        return list(
            (
                await self._session.execute(
                    select(CrawlSnapshot).where(
                        CrawlSnapshot.company_id == company.id, CrawlSnapshot.is_current
                    )
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    def _extract_hrefs(html: str, base_url: str) -> list[str]:
        """Every outbound `<a href>`, absolute-resolved — unlike Module 4's
        `extract_internal_links`, this is deliberately NOT filtered to
        same-domain links, since a social profile link always points to a
        different domain."""
        tree = HTMLParser(html)
        hrefs = []
        for anchor in tree.css("a[href]"):
            href = (anchor.attributes.get("href") or "").strip()
            if not href or href.startswith(_SKIP_SCHEMES):
                continue
            hrefs.append(urljoin(base_url, href))
        return hrefs

    async def _upsert_profile(self, company: Company, match: SocialLinkMatch) -> None:
        existing = (
            await self._session.execute(
                select(SocialProfile).where(
                    SocialProfile.company_id == company.id, SocialProfile.url == match.url
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.handle = match.handle
            existing.platform = match.platform.value
            return
        self._session.add(
            SocialProfile(
                company_id=company.id,
                platform=match.platform.value,
                url=match.url,
                handle=match.handle,
                discovered_at=datetime.now(UTC),
            )
        )

    async def _log(self, job: ScrapeJob, level: LogLevel, message: str, context: dict) -> None:
        self._session.add(
            JobLog(scrape_job_id=job.id, level=level.value, message=message, context=context)
        )
        logger.log(_PY_LOG_LEVEL[level], "%s: %s", message, context)


_PY_LOG_LEVEL = {
    LogLevel.DEBUG: logging.DEBUG,
    LogLevel.INFO: logging.INFO,
    LogLevel.WARNING: logging.WARNING,
    LogLevel.ERROR: logging.ERROR,
    LogLevel.CRITICAL: logging.CRITICAL,
}
