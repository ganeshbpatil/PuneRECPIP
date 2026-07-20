"""Creates the `scrape_jobs` row a discovery run is driven by. Kept separate
from `service.py` (which only knows how to *run* a job, not create one) so an
API endpoint can create discovery jobs without importing HTTP/Celery code."""

from corelib.enums import ScrapeJobStatus, ScrapeJobType
from corelib.models import ScrapeJob
from sqlalchemy.ext.asyncio import AsyncSession

from worker.discovery.service import DEFAULT_MAX_PAGES_PER_QUERY


async def create_discovery_job(
    session: AsyncSession,
    *,
    keywords: list[str],
    locations: list[str],
    site_profile: str,
    max_pages_per_query: int = DEFAULT_MAX_PAGES_PER_QUERY,
) -> ScrapeJob:
    if not keywords or not locations:
        raise ValueError("at least one keyword and one location are required")

    job = ScrapeJob(
        job_type=ScrapeJobType.DISCOVERY.value,
        status=ScrapeJobStatus.PENDING.value,
        queue_name="discovery",
        payload={
            "keywords": keywords,
            "locations": locations,
            "site_profile": site_profile,
            "max_pages_per_query": max_pages_per_query,
        },
    )
    session.add(job)
    await session.commit()
    return job
