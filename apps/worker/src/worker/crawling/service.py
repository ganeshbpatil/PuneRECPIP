"""Crawl orchestration: consumes a pending `job_type=crawl` ScrapeJob left by
Module 3, fetches a bounded set of pages for the company's website (home plus
up to `max_pages - 1` keyword-classified internal pages), extracts and stores
content, aggregates contact info onto the company, and hands off to Module 5
via a pending `job_type=extraction` ScrapeJob — the same durable-ledger
pattern Module 3 established for the discovery -> crawl hand-off.

Checkpointed and committed after every page (same rationale as
worker.discovery.service.DiscoveryService: a crash mid-run must lose at most
one in-flight page, never previously completed ones).
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

from corelib.enums import (
    CompanyStatus,
    EmailType,
    LogLevel,
    PageType,
    PhoneType,
    ScrapeJobStatus,
    ScrapeJobType,
    WebsiteStatus,
)
from corelib.models import (
    Company,
    CrawlSnapshot,
    EmailAddress,
    JobLog,
    PhoneNumber,
    ScrapeJob,
    Website,
)
from corelib.storage import ObjectStorage
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from worker.crawling.browser import BrowserPool, FetchedPage
from worker.crawling.contact_extraction import extract_emails, extract_phones
from worker.crawling.content_extraction import extract_clean_html, html_to_markdown
from worker.crawling.link_extraction import extract_internal_links
from worker.crawling.page_classifier import classify_link
from worker.net.ratelimit import DomainRateLimiter
from worker.net.robots import RobotsCache

logger = logging.getLogger(__name__)


@dataclass
class CrawlRunResult:
    pages_crawled: int = 0
    emails_found: int = 0
    phones_found: int = 0
    errors: list[str] = field(default_factory=list)


class CrawlService:
    def __init__(
        self,
        session: AsyncSession,
        browser: BrowserPool,
        storage: ObjectStorage,
        rate_limiter: DomainRateLimiter,
        robots: RobotsCache,
        *,
        max_pages_per_company: int,
    ):
        self._session = session
        self._browser = browser
        self._storage = storage
        self._rate_limiter = rate_limiter
        self._robots = robots
        self._max_pages = max_pages_per_company

    async def run(self, job: ScrapeJob) -> CrawlRunResult:
        result = CrawlRunResult(**(job.result or {}))

        job.status = ScrapeJobStatus.RUNNING.value
        if job.started_at is None:
            job.started_at = datetime.now(UTC)
        await self._session.commit()

        try:
            company = await self._load_company(job)
            website = await self._load_primary_website(company)
            await self._run_crawl(job, company, website, result)
            job.status = ScrapeJobStatus.SUCCEEDED.value
        except Exception as exc:  # noqa: BLE001 - persist failure state before re-raising
            job.status = ScrapeJobStatus.FAILED.value
            job.error_message = str(exc)
            await self._log(job, LogLevel.ERROR, "crawl job failed", {"error": str(exc)})
            job.result = _result_to_dict(result)
            job.finished_at = datetime.now(UTC)
            await self._session.commit()
            raise
        else:
            job.result = _result_to_dict(result)
            job.finished_at = datetime.now(UTC)
            await self._session.commit()

        return result

    async def _load_company(self, job: ScrapeJob) -> Company:
        if job.company_id is None:
            raise ValueError("crawl jobs must have company_id set")
        company = (
            await self._session.execute(select(Company).where(Company.id == job.company_id))
        ).scalar_one_or_none()
        if company is None:
            raise ValueError(f"company {job.company_id} not found")
        return company

    async def _load_primary_website(self, company: Company) -> Website:
        websites = (
            await self._session.execute(
                select(Website).where(Website.company_id == company.id).order_by(
                    Website.is_primary.desc(), Website.created_at.asc()
                )
            )
        ).scalars().all()
        if not websites:
            raise ValueError(f"company {company.id} has no website to crawl")
        return websites[0]

    async def _run_crawl(
        self, job: ScrapeJob, company: Company, website: Website, result: CrawlRunResult
    ) -> None:
        checkpoint = job.checkpoint or {"visited": [], "candidate_pages": None}
        visited: list[str] = checkpoint["visited"]
        candidate_pages: list[dict] | None = checkpoint["candidate_pages"]

        if website.url not in visited:
            homepage = await self._fetch_and_save(job, company, website, website.url, PageType.HOME)
            visited.append(website.url)
            candidate_pages = self._select_candidate_pages(homepage, website.url)
            checkpoint = {"visited": visited, "candidate_pages": candidate_pages}
            job.checkpoint = checkpoint
            await self._session.commit()
            result.pages_crawled += 1

        assert candidate_pages is not None
        for candidate in candidate_pages:
            if len(visited) >= self._max_pages:
                break
            if candidate["url"] in visited:
                continue
            try:
                await self._fetch_and_save(
                    job, company, website, candidate["url"], PageType(candidate["page_type"])
                )
            except Exception as exc:  # noqa: BLE001 - one bad page shouldn't fail the whole crawl
                result.errors.append(f"{candidate['url']}: {exc}")
                await self._log(
                    job,
                    LogLevel.ERROR,
                    "page fetch failed, skipping",
                    {"url": candidate["url"], "error": str(exc)},
                )
                visited.append(candidate["url"])  # don't retry a known-bad page on resume
                job.checkpoint = {"visited": visited, "candidate_pages": candidate_pages}
                await self._session.commit()
                continue

            visited.append(candidate["url"])
            job.checkpoint = {"visited": visited, "candidate_pages": candidate_pages}
            await self._session.commit()
            result.pages_crawled += 1

        await self._aggregate_contacts(job, company, result)

        company.last_crawled_at = datetime.now(UTC)
        company.status = CompanyStatus.CRAWLED.value
        website.last_checked_at = datetime.now(UTC)
        website.status = WebsiteStatus.ACTIVE.value

        self._session.add(
            ScrapeJob(
                job_type=ScrapeJobType.EXTRACTION.value,
                status=ScrapeJobStatus.PENDING.value,
                company_id=company.id,
                payload={"reason": "crawled", "crawl_job_id": str(job.id)},
            )
        )
        await self._session.commit()

    def _select_candidate_pages(self, homepage: FetchedPage, base_url: str) -> list[dict]:
        links = extract_internal_links(homepage.html, base_url)
        budget = max(0, self._max_pages - 1)
        seen_types: set[PageType] = set()
        candidates: list[dict] = []

        for href, text in links:
            if len(candidates) >= budget:
                break
            page_type = classify_link(href, text)
            if page_type in (PageType.OTHER, PageType.HOME) or page_type in seen_types:
                continue
            seen_types.add(page_type)
            candidates.append({"url": href, "page_type": page_type.value})

        return candidates

    async def _fetch_and_save(
        self,
        job: ScrapeJob,
        company: Company,
        website: Website,
        url: str,
        page_type: PageType,
    ) -> FetchedPage:
        if not await self._robots.is_allowed(url):
            raise PermissionError(f"robots.txt disallows fetching {url}")

        await self._rate_limiter.acquire(urlsplit(url).netloc)
        fetched = await self._browser.fetch(url)

        clean_html = extract_clean_html(fetched.html, url)
        markdown = html_to_markdown(clean_html)
        emails = extract_emails(fetched.html)
        phones = extract_phones(fetched.html)
        content_hash = hashlib.sha256(clean_html.encode("utf-8")).hexdigest()

        key_prefix = f"crawls/{company.id}/{page_type.value}/{content_hash[:16]}"
        await self._storage.put(
            f"{key_prefix}/raw.html", fetched.html.encode(), content_type="text/html"
        )
        await self._storage.put(
            f"{key_prefix}/clean.html", clean_html.encode(), content_type="text/html"
        )
        await self._storage.put(
            f"{key_prefix}/content.md", markdown.encode(), content_type="text/markdown"
        )
        await self._storage.put(
            f"{key_prefix}/screenshot.png", fetched.screenshot, content_type="image/png"
        )

        await self._session.execute(
            update(CrawlSnapshot)
            .where(CrawlSnapshot.company_id == company.id, CrawlSnapshot.url == url)
            .values(is_current=False)
        )
        self._session.add(
            CrawlSnapshot(
                company_id=company.id,
                scrape_job_id=job.id,
                website_id=website.id,
                url=url,
                page_type=page_type.value,
                http_status=fetched.http_status,
                raw_html_key=f"{key_prefix}/raw.html",
                clean_html_key=f"{key_prefix}/clean.html",
                markdown_key=f"{key_prefix}/content.md",
                screenshot_key=f"{key_prefix}/screenshot.png",
                content_hash=content_hash,
                extracted_emails=emails,
                extracted_phones=phones,
                extracted_links=[href for href, _ in extract_internal_links(fetched.html, url)],
                is_current=True,
                crawled_at=datetime.now(UTC),
            )
        )
        await self._log(
            job,
            LogLevel.INFO,
            "crawled page",
            {
                "url": url,
                "page_type": page_type.value,
                "emails": len(emails),
                "phones": len(phones),
            },
        )
        return fetched

    async def _aggregate_contacts(
        self, job: ScrapeJob, company: Company, result: CrawlRunResult
    ) -> None:
        snapshots = (
            await self._session.execute(
                select(CrawlSnapshot).where(
                    CrawlSnapshot.company_id == company.id, CrawlSnapshot.is_current
                )
            )
        ).scalars().all()

        existing_emails = set(
            (
                await self._session.execute(
                    select(EmailAddress.email).where(EmailAddress.company_id == company.id)
                )
            ).scalars().all()
        )
        existing_phones = set(
            (
                await self._session.execute(
                    select(PhoneNumber.phone_number).where(PhoneNumber.company_id == company.id)
                )
            ).scalars().all()
        )

        for snapshot in snapshots:
            for email in snapshot.extracted_emails:
                if email in existing_emails:
                    continue
                existing_emails.add(email)
                self._session.add(
                    EmailAddress(
                        company_id=company.id,
                        email=email,
                        email_type=EmailType.GENERAL.value,
                        source_url=snapshot.url,
                    )
                )
                result.emails_found += 1

            for phone in snapshot.extracted_phones:
                if phone in existing_phones:
                    continue
                existing_phones.add(phone)
                self._session.add(
                    PhoneNumber(
                        company_id=company.id,
                        phone_number=phone,
                        phone_type=PhoneType.MOBILE.value,
                        source_url=snapshot.url,
                    )
                )
                result.phones_found += 1

        await self._log(
            job,
            LogLevel.INFO,
            "aggregated contacts",
            {"emails_found": result.emails_found, "phones_found": result.phones_found},
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


def _result_to_dict(result: CrawlRunResult) -> dict:
    return {
        "pages_crawled": result.pages_crawled,
        "emails_found": result.emails_found,
        "phones_found": result.phones_found,
        "errors": result.errors,
    }
