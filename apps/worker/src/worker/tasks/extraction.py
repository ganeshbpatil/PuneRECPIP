"""Celery entrypoint for AI enrichment jobs. The task itself is a thin, sync
wrapper — all real logic lives in EnrichmentService so it can be unit/
integration-tested without Celery/Redis or a live AI provider credential."""

import asyncio
import logging
from datetime import UTC, datetime

import anthropic
import openai
from corelib.enums import ScrapeJobStatus
from corelib.models import ScrapeJob
from sqlalchemy import select

from worker.celery_app import app
from worker.core.config import Settings, get_settings
from worker.core.db import get_session_factory
from worker.core.storage import get_object_storage
from worker.enrichment.embeddings import OpenAIEmbeddingProvider
from worker.enrichment.extractors import AIExtractor, ClaudeExtractor, OpenAIExtractor
from worker.enrichment.service import EnrichmentService

logger = logging.getLogger(__name__)


def _build_extractor(settings: Settings) -> AIExtractor:
    if settings.enrichment_provider == "claude":
        client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key, max_retries=settings.enrichment_max_retries
        )
        return ClaudeExtractor(client, model=settings.enrichment_claude_model)
    if settings.enrichment_provider == "openai":
        client = openai.AsyncOpenAI(
            api_key=settings.openai_api_key, max_retries=settings.enrichment_max_retries
        )
        return OpenAIExtractor(client, model=settings.enrichment_openai_model)
    raise ValueError(f"unknown enrichment_provider: {settings.enrichment_provider!r}")


@app.task(
    name="worker.tasks.extraction.run_extraction_job",
    bind=True,
    autoretry_for=(ConnectionError, OSError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def run_extraction_job(self, job_id: str) -> dict:
    """Runs the extraction ScrapeJob identified by `job_id`. Unlike discovery/
    crawl jobs, re-invoking after a failure re-runs the whole AI call rather
    than resuming a checkpoint — see EnrichmentService's module docstring."""
    return asyncio.run(_run_extraction_job_async(job_id))


async def _run_extraction_job_async(job_id: str) -> dict:
    settings = get_settings()
    session_factory = get_session_factory()
    storage = get_object_storage(settings)

    async with session_factory() as session:
        job = (
            await session.execute(select(ScrapeJob).where(ScrapeJob.id == job_id))
        ).scalar_one()

        # AI provider SDK clients validate credentials eagerly at construction
        # (openai.AsyncOpenAI raises immediately with no api_key; anthropic's
        # doesn't, but the same principle applies to any future provider) —
        # unlike httpx.AsyncClient/BrowserPool in the discovery/crawl tasks,
        # which never fail until a real request is made. That construction
        # therefore happens here, inside the same try/except that
        # EnrichmentService.run() itself uses to persist failure state, so a
        # missing/invalid credential still lands the job in `failed` with a
        # clear error instead of leaving it stuck in `pending` forever.
        try:
            extractor = _build_extractor(settings)
            embeddings = OpenAIEmbeddingProvider(
                openai.AsyncOpenAI(
                    api_key=settings.openai_api_key,
                    max_retries=settings.enrichment_max_retries,
                ),
                model=settings.enrichment_embedding_model,
            )
        except Exception as exc:
            job.status = ScrapeJobStatus.FAILED.value
            job.error_message = f"failed to construct AI provider client: {exc}"
            job.finished_at = datetime.now(UTC)
            await session.commit()
            raise

        service = EnrichmentService(
            session,
            storage,
            extractor,
            embeddings,
            max_content_chars=settings.enrichment_max_content_chars,
            model_name=(
                settings.enrichment_claude_model
                if settings.enrichment_provider == "claude"
                else settings.enrichment_openai_model
            ),
        )
        result = await service.run(job)

    logger.info("extraction job %s finished: %s", job_id, result)
    return {
        "business_category": result.business_category,
        "specializations_recorded": result.specializations_recorded,
        "service_areas_recorded": result.service_areas_recorded,
        "developers_recorded": result.developers_recorded,
        "confidence_score": result.confidence_score,
    }
