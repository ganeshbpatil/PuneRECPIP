"""Discovery orchestration: runs a keyword x location query grid against a
DiscoverySource, paginating each query, deduping against what's already in the
database, persisting new companies, and checkpointing progress after every
page so a crashed/restarted job resumes instead of re-running from scratch.

Full fuzzy/cross-field duplicate detection is Module 8 — this only needs
"have I already saved this exact listing," answered by domain or exact-name-
slug equality (see normalize.py docstring).
"""

import logging
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime

from corelib.enums import CompanyStatus, DataSource, LogLevel, ScrapeJobStatus, ScrapeJobType
from corelib.models import Company, JobLog, PhoneNumber, ScrapeJob, Website
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from worker.discovery.models import DiscoveredListing, SearchQuery
from worker.discovery.normalize import normalize_domain, normalize_india_phone, slugify
from worker.discovery.sources import DiscoverySource

logger = logging.getLogger(__name__)

DEFAULT_MAX_PAGES_PER_QUERY = 20


@dataclass
class DiscoveryRunResult:
    companies_discovered: int = 0
    companies_skipped_duplicate: int = 0
    queries_run: int = 0
    errors: list[str] = field(default_factory=list)


class DiscoveryService:
    def __init__(self, session: AsyncSession, source: DiscoverySource):
        self._session = session
        self._source = source

    async def run(self, job: ScrapeJob) -> DiscoveryRunResult:
        # `result` must exist before the try block starts so the except clause
        # can always persist it, even if payload parsing itself is what failed.
        result = DiscoveryRunResult(**(job.result or {}))

        job.status = ScrapeJobStatus.RUNNING.value
        if job.started_at is None:
            job.started_at = datetime.now(UTC)
        await self._session.commit()

        try:
            keywords: list[str] = job.payload["keywords"]
            locations: list[str] = job.payload["locations"]
            max_pages = job.payload.get("max_pages_per_query", DEFAULT_MAX_PAGES_PER_QUERY)
            queries = [
                SearchQuery(keyword=k, location=loc) for k in keywords for loc in locations
            ]
            checkpoint = job.checkpoint or {"query_index": 0, "next_page": 1}

            resume_index = checkpoint["query_index"]
            for query_index in range(resume_index, len(queries)):
                query = queries[query_index]
                start_page = checkpoint["next_page"] if query_index == resume_index else 1
                await self._run_query(job, query, query_index, start_page, max_pages, result)
                result.queries_run += 1

            job.status = ScrapeJobStatus.SUCCEEDED.value
        except Exception as exc:  # noqa: BLE001 - persist failure state before re-raising
            job.status = ScrapeJobStatus.FAILED.value
            job.error_message = str(exc)
            await self._log(job, LogLevel.ERROR, "discovery job failed", {"error": str(exc)})
            job.result = _result_to_dict(result)
            job.finished_at = datetime.now(UTC)
            await self._session.commit()
            raise
        else:
            job.result = _result_to_dict(result)
            job.finished_at = datetime.now(UTC)
            await self._session.commit()

        return result

    async def _run_query(
        self,
        job: ScrapeJob,
        query: SearchQuery,
        query_index: int,
        start_page: int,
        max_pages: int,
        result: DiscoveryRunResult,
    ) -> None:
        page_number = start_page
        while page_number <= max_pages:
            try:
                page = await self._source.search(query, page_number)
            except Exception as exc:  # noqa: BLE001 - one bad query shouldn't fail the whole job
                result.errors.append(f"{query.keyword}/{query.location} p{page_number}: {exc}")
                await self._log(
                    job,
                    LogLevel.ERROR,
                    "query page fetch failed, skipping to next query",
                    {"keyword": query.keyword, "location": query.location, "page": page_number,
                     "error": str(exc)},
                )
                break

            for listing in page.listings:
                if await self._save_listing(job, listing, query):
                    result.companies_discovered += 1
                else:
                    result.companies_skipped_duplicate += 1

            advance = page.has_next and page_number < max_pages
            job.checkpoint = {
                "query_index": query_index if advance else query_index + 1,
                "next_page": page_number + 1 if advance else 1,
            }
            await self._session.commit()

            if not advance:
                break
            page_number += 1

    async def _save_listing(
        self, job: ScrapeJob, listing: DiscoveredListing, query: SearchQuery
    ) -> bool:
        domain = normalize_domain(listing.website_url) if listing.website_url else None

        if await self._already_known(domain, listing.name):
            await self._log(
                job,
                LogLevel.DEBUG,
                "skipped duplicate listing",
                {"name": listing.name, "domain": domain},
            )
            return False

        company = Company(
            name=listing.name,
            slug=await self._unique_slug(listing.name),
            status=CompanyStatus.DISCOVERED.value,
            description=listing.snippet,
            discovered_at=datetime.now(UTC),
        )
        self._session.add(company)
        await self._session.flush()  # assigns company.id for child rows below

        if listing.website_url:
            self._session.add(
                Website(company_id=company.id, url=listing.website_url, domain=domain)
            )

        if listing.phone_raw:
            normalized = normalize_india_phone(listing.phone_raw)
            self._session.add(
                PhoneNumber(
                    company_id=company.id,
                    phone_number=normalized or listing.phone_raw,
                    raw_value=listing.phone_raw,
                    source_url=listing.source_listing_url,
                )
            )

        # Durable hand-off to Module 4: a pending crawl job row now exists in the
        # ledger regardless of whether a Celery crawl task is registered yet.
        self._session.add(
            ScrapeJob(
                job_type=ScrapeJobType.CRAWL.value,
                status=ScrapeJobStatus.PENDING.value,
                company_id=company.id,
                payload={"reason": "discovered", "discovery_job_id": str(job.id)},
            )
        )

        await self._log(
            job,
            LogLevel.INFO,
            "discovered company",
            {
                "company_id": str(company.id),
                "name": listing.name,
                "domain": domain,
                "keyword": query.keyword,
                "location": query.location,
                "source": DataSource.DIRECTORY.value,
            },
        )
        return True

    async def _already_known(self, domain: str | None, name: str) -> bool:
        if domain:
            existing = await self._session.execute(
                select(Website.id).where(Website.domain == domain).limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                return True
            return False

        # No website to key off of: fall back to exact-name-slug match. A
        # conservative heuristic (two distinct companies could share a slug)
        # that Module 8's fuzzy matching supersedes.
        existing = await self._session.execute(
            select(Company.id).where(Company.slug == slugify(name)).limit(1)
        )
        return existing.scalar_one_or_none() is not None

    async def _unique_slug(self, name: str) -> str:
        base = slugify(name)
        candidate = base
        for _ in range(5):
            existing = await self._session.execute(
                select(Company.id).where(Company.slug == candidate).limit(1)
            )
            if existing.scalar_one_or_none() is None:
                return candidate
            candidate = slugify(name, suffix=secrets.token_hex(3))
        raise RuntimeError(f"could not generate a unique slug for {name!r}")

    async def _log(
        self, job: ScrapeJob, level: LogLevel, message: str, context: dict
    ) -> None:
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


def _result_to_dict(result: DiscoveryRunResult) -> dict:
    return {
        "companies_discovered": result.companies_discovered,
        "companies_skipped_duplicate": result.companies_skipped_duplicate,
        "queries_run": result.queries_run,
        "errors": result.errors,
    }
