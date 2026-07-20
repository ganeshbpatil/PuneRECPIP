"""AI enrichment orchestration: consumes a pending `job_type=extraction`
ScrapeJob left by Module 4, assembles the company's crawled Markdown into one
prompt, calls an AIExtractor for a structured profile, and projects that
profile onto `ai_summaries` plus the normalized tables it summarizes
(`company_specializations`, `company_categories`, `service_areas`,
`company_developer_partnerships`) and `companies` itself.

Unlike DiscoveryService/CrawlService, this does not checkpoint page-by-page:
the unit of work here is a single AI call per company, not a naturally
paginated loop, so there's nothing meaningful to resume mid-way through — a
retry simply re-runs the whole (idempotent-in-effect, is_current-versioned)
pass. Transient provider failures are retried by the Anthropic/OpenAI SDKs'
own built-in `max_retries`, not a hand-rolled loop here.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from corelib.enums import CompanyStatus, DataSource, LogLevel, ScrapeJobStatus, ServiceAreaType
from corelib.models import (
    AISummary,
    Company,
    CompanyCategory,
    CompanyDeveloperPartnership,
    CompanySpecialization,
    CrawlSnapshot,
    JobLog,
    ScrapeJob,
    ServiceArea,
)
from corelib.schemas.enrichment import CompanyExtraction
from corelib.storage import ObjectNotFoundError, ObjectStorage
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from worker.enrichment.category_matching import match_or_create_business_category
from worker.enrichment.developer_matching import match_or_create_developer
from worker.enrichment.embeddings import EmbeddingProvider
from worker.enrichment.extractors import AIExtractor

logger = logging.getLogger(__name__)

# Read order for assembling the prompt — most identity/context-bearing pages
# first, in case the content budget truncates the tail.
_PAGE_TYPE_ORDER = ["home", "about", "services", "contact", "team", "projects", "developers"]


@dataclass
class EnrichmentRunResult:
    business_category: str | None = None
    specializations_recorded: int = 0
    service_areas_recorded: int = 0
    developers_recorded: int = 0
    confidence_score: float | None = None


class EnrichmentService:
    def __init__(
        self,
        session: AsyncSession,
        storage: ObjectStorage,
        extractor: AIExtractor,
        embeddings: EmbeddingProvider,
        *,
        max_content_chars: int,
        model_name: str,
    ):
        self._session = session
        self._storage = storage
        self._extractor = extractor
        self._embeddings = embeddings
        self._max_content_chars = max_content_chars
        self._model_name = model_name

    async def run(self, job: ScrapeJob) -> EnrichmentRunResult:
        result = EnrichmentRunResult()

        job.status = ScrapeJobStatus.RUNNING.value
        if job.started_at is None:
            job.started_at = datetime.now(UTC)
        await self._session.commit()

        try:
            company = await self._load_company(job)
            content = await self._assemble_content(company)
            extraction = await self._extractor.extract(company.name, content)
            embedding = await self._embeddings.embed(extraction.summary_markdown)

            await self._persist_summary(job, company, extraction, embedding)
            await self._persist_category(job, company, extraction, result)
            await self._persist_specializations(job, company, extraction, result)
            await self._persist_service_areas(job, company, extraction, result)
            await self._persist_developers(job, company, extraction, result)

            company.status = CompanyStatus.ENRICHED.value
            company.last_enriched_at = datetime.now(UTC)
            company.confidence_score = extraction.confidence_score
            if extraction.year_established is not None:
                company.year_established = extraction.year_established
            result.confidence_score = extraction.confidence_score

            job.status = ScrapeJobStatus.SUCCEEDED.value
        except Exception as exc:  # noqa: BLE001 - persist failure state before re-raising
            job.status = ScrapeJobStatus.FAILED.value
            job.error_message = str(exc)
            await self._log(job, LogLevel.ERROR, "enrichment job failed", {"error": str(exc)})
            job.finished_at = datetime.now(UTC)
            await self._session.commit()
            raise
        else:
            job.result = {
                "business_category": result.business_category,
                "specializations_recorded": result.specializations_recorded,
                "service_areas_recorded": result.service_areas_recorded,
                "developers_recorded": result.developers_recorded,
                "confidence_score": result.confidence_score,
            }
            job.finished_at = datetime.now(UTC)
            await self._session.commit()

        return result

    async def _load_company(self, job: ScrapeJob) -> Company:
        if job.company_id is None:
            raise ValueError("extraction jobs must have company_id set")
        company = (
            await self._session.execute(select(Company).where(Company.id == job.company_id))
        ).scalar_one_or_none()
        if company is None:
            raise ValueError(f"company {job.company_id} not found")
        return company

    async def _assemble_content(self, company: Company) -> str:
        snapshots = (
            await self._session.execute(
                select(CrawlSnapshot).where(
                    CrawlSnapshot.company_id == company.id, CrawlSnapshot.is_current
                )
            )
        ).scalars().all()
        if not snapshots:
            raise ValueError(f"company {company.id} has no crawled content to enrich")

        snapshots.sort(
            key=lambda s: _PAGE_TYPE_ORDER.index(s.page_type)
            if s.page_type in _PAGE_TYPE_ORDER
            else len(_PAGE_TYPE_ORDER)
        )

        sections: list[str] = []
        budget = self._max_content_chars
        for snapshot in snapshots:
            if budget <= 0 or not snapshot.markdown_key:
                continue
            try:
                markdown = (await self._storage.get(snapshot.markdown_key)).decode("utf-8")
            except ObjectNotFoundError:
                logger.warning("markdown artifact missing for snapshot %s", snapshot.id)
                continue
            heading = f"## {snapshot.page_type.title()} page ({snapshot.url})"
            section = f"{heading}\n\n{markdown[:budget]}"
            sections.append(section)
            budget -= len(section)

        return "\n\n".join(sections)

    async def _persist_summary(
        self,
        job: ScrapeJob,
        company: Company,
        extraction: CompanyExtraction,
        embedding: list[float],
    ) -> None:
        await self._session.execute(
            update(AISummary)
            .where(AISummary.company_id == company.id, AISummary.is_current)
            .values(is_current=False)
        )
        self._session.add(
            AISummary(
                company_id=company.id,
                summary_markdown=extraction.summary_markdown,
                structured_json=extraction.model_dump(mode="json"),
                model_name=self._model_name,
                prompt_version="v1",
                confidence_score=extraction.confidence_score,
                embedding=embedding,
                is_current=True,
                generated_at=datetime.now(UTC),
            )
        )
        await self._log(
            job,
            LogLevel.INFO,
            "recorded AI summary",
            {"confidence_score": extraction.confidence_score},
        )

    async def _persist_category(
        self,
        job: ScrapeJob,
        company: Company,
        extraction: CompanyExtraction,
        result: EnrichmentRunResult,
    ) -> None:
        category = await match_or_create_business_category(
            self._session, extraction.business_category
        )
        result.business_category = category.name

        await self._session.execute(
            update(CompanyCategory)
            .where(CompanyCategory.company_id == company.id, CompanyCategory.is_primary)
            .values(is_primary=False)
        )
        existing = (
            await self._session.execute(
                select(CompanyCategory).where(
                    CompanyCategory.company_id == company.id,
                    CompanyCategory.category_id == category.id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.is_primary = True
        else:
            self._session.add(
                CompanyCategory(company_id=company.id, category_id=category.id, is_primary=True)
            )
        await self._log(
            job, LogLevel.INFO, "matched business category", {"category": category.name}
        )

    async def _persist_specializations(
        self,
        job: ScrapeJob,
        company: Company,
        extraction: CompanyExtraction,
        result: EnrichmentRunResult,
    ) -> None:
        for assessment in extraction.specializations:
            existing = (
                await self._session.execute(
                    select(CompanySpecialization).where(
                        CompanySpecialization.company_id == company.id,
                        CompanySpecialization.specialization == assessment.specialization.value,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.confidence_score = assessment.confidence
                existing.source = DataSource.AI_EXTRACTION.value
            else:
                self._session.add(
                    CompanySpecialization(
                        company_id=company.id,
                        specialization=assessment.specialization.value,
                        confidence_score=assessment.confidence,
                        source=DataSource.AI_EXTRACTION.value,
                    )
                )
            result.specializations_recorded += 1

    async def _persist_service_areas(
        self,
        job: ScrapeJob,
        company: Company,
        extraction: CompanyExtraction,
        result: EnrichmentRunResult,
    ) -> None:
        for area_name in extraction.areas_served:
            existing = (
                await self._session.execute(
                    select(ServiceArea).where(
                        ServiceArea.company_id == company.id, ServiceArea.locality == area_name
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.confidence_score = extraction.confidence_score
                continue
            self._session.add(
                ServiceArea(
                    company_id=company.id,
                    area_type=ServiceAreaType.NEIGHBOURHOOD.value,
                    locality=area_name,
                    source=DataSource.AI_EXTRACTION.value,
                    confidence_score=extraction.confidence_score,
                )
            )
            result.service_areas_recorded += 1

    async def _persist_developers(
        self,
        job: ScrapeJob,
        company: Company,
        extraction: CompanyExtraction,
        result: EnrichmentRunResult,
    ) -> None:
        for developer_name in extraction.developers_represented:
            developer = await match_or_create_developer(self._session, developer_name)
            existing = (
                await self._session.execute(
                    select(CompanyDeveloperPartnership).where(
                        CompanyDeveloperPartnership.company_id == company.id,
                        CompanyDeveloperPartnership.developer_id == developer.id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.confidence_score = extraction.confidence_score
                existing.is_active = True
            else:
                self._session.add(
                    CompanyDeveloperPartnership(
                        company_id=company.id,
                        developer_id=developer.id,
                        confidence_score=extraction.confidence_score,
                    )
                )
            result.developers_recorded += 1

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
