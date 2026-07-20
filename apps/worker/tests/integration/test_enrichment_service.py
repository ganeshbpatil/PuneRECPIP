"""EnrichmentService against real Postgres (pg_trgm-backed category matching
is a real database feature, same rationale as test_category_matching.py) and
a real LocalFilesystemObjectStorage. The AI provider and embedding provider
are the one deliberately-faked dependency here — this repo has no
ANTHROPIC_API_KEY/OPENAI_API_KEY to call a real provider (see
docs/modules/05-ai-enrichment.md); extractors.py itself is verified
structurally against realistic mocked HTTP responses in test_extractors.py.
"""

import pytest
from corelib.enums import CompanyStatus, PageType, ScrapeJobStatus, ScrapeJobType
from corelib.models import (
    AISummary,
    BusinessCategory,
    Company,
    CompanyCategory,
    CompanyDeveloperPartnership,
    CompanySpecialization,
    CrawlSnapshot,
    Developer,
    JobLog,
    ScrapeJob,
    ServiceArea,
)
from corelib.schemas.enrichment import CompanyExtraction, SpecializationAssessment
from corelib.storage import LocalFilesystemObjectStorage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from worker.enrichment.service import EnrichmentService

pytestmark = pytest.mark.asyncio

FAKE_EMBEDDING = [0.01] * 1536


class FakeAIExtractor:
    def __init__(self, extraction: CompanyExtraction | Exception):
        self._extraction = extraction
        self.calls: list[tuple[str, str]] = []

    async def extract(self, company_name_hint: str, content: str) -> CompanyExtraction:
        self.calls.append((company_name_hint, content))
        if isinstance(self._extraction, Exception):
            raise self._extraction
        return self._extraction


class FakeEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        return FAKE_EMBEDDING


def _sample_extraction(**overrides) -> CompanyExtraction:
    defaults = dict(
        company_name="Acme Realty Pune",
        business_category="Broker",
        services=["Residential resale", "Rentals"],
        specializations=[
            SpecializationAssessment(specialization="residential_sales", confidence=0.9),
            SpecializationAssessment(specialization="residential_leasing", confidence=0.7),
        ],
        residential_vs_commercial_focus="residential",
        sales_vs_leasing_focus="both",
        areas_served=["Kothrud", "Baner"],
        year_established=2010,
        developers_represented=["Kolte Patil Developers"],
        confidence_score=0.85,
        summary_markdown=(
            "# Acme Realty Pune\nA residential broker in Kothrud and Baner since 2010."
        ),
    )
    defaults.update(overrides)
    return CompanyExtraction(**defaults)


async def _make_enriched_company(
    session: AsyncSession, storage: LocalFilesystemObjectStorage
) -> Company:
    company = Company(name="Acme Realty Pune", slug="acme-realty-pune-enrichment-test")
    session.add(company)
    await session.flush()

    for page_type, markdown in [
        (PageType.HOME, "# Acme Realty Pune\nWelcome to our site."),
        (PageType.ABOUT, "# About\nServing Kothrud and Baner since 2010."),
    ]:
        key = f"crawls/{company.id}/{page_type.value}/content.md"
        await storage.put(key, markdown.encode(), content_type="text/markdown")
        session.add(
            CrawlSnapshot(
                company_id=company.id,
                url=f"https://acme.example/{page_type.value}",
                page_type=page_type.value,
                markdown_key=key,
                is_current=True,
            )
        )
    await session.flush()
    return company


async def _make_job(session: AsyncSession, company: Company) -> ScrapeJob:
    job = ScrapeJob(
        job_type=ScrapeJobType.EXTRACTION.value,
        status=ScrapeJobStatus.PENDING.value,
        company_id=company.id,
    )
    session.add(job)
    await session.commit()
    return job


def _make_service(extractor: FakeAIExtractor, session: AsyncSession, storage) -> EnrichmentService:
    return EnrichmentService(
        session,
        storage,
        extractor,
        FakeEmbeddingProvider(),
        max_content_chars=24000,
        model_name="claude-sonnet-5",
    )


async def test_full_enrichment_persists_summary_and_all_projections(
    session: AsyncSession, tmp_path
):
    storage = LocalFilesystemObjectStorage(tmp_path)
    company = await _make_enriched_company(session, storage)
    job = await _make_job(session, company)
    extractor = FakeAIExtractor(_sample_extraction())

    result = await _make_service(extractor, session, storage).run(job)

    assert job.status == ScrapeJobStatus.SUCCEEDED.value
    assert result.business_category == "Broker"
    assert result.specializations_recorded == 2
    assert result.service_areas_recorded == 2
    assert result.developers_recorded == 1
    assert result.confidence_score == 0.85

    summary = (
        await session.execute(select(AISummary).where(AISummary.company_id == company.id))
    ).scalar_one()
    assert summary.is_current is True
    assert summary.embedding is not None
    assert summary.structured_json["business_category"] == "Broker"
    assert "Kothrud" in summary.summary_markdown

    primary_category_name = (
        await session.execute(
            select(BusinessCategory.name)
            .join(CompanyCategory, CompanyCategory.category_id == BusinessCategory.id)
            .where(CompanyCategory.company_id == company.id, CompanyCategory.is_primary)
        )
    ).scalar_one()
    assert primary_category_name == "Broker"

    specializations = (
        await session.execute(
            select(CompanySpecialization).where(CompanySpecialization.company_id == company.id)
        )
    ).scalars().all()
    assert {s.specialization for s in specializations} == {
        "residential_sales",
        "residential_leasing",
    }

    areas = (
        await session.execute(select(ServiceArea).where(ServiceArea.company_id == company.id))
    ).scalars().all()
    assert {a.locality for a in areas} == {"Kothrud", "Baner"}

    partnership = (
        await session.execute(
            select(CompanyDeveloperPartnership).where(
                CompanyDeveloperPartnership.company_id == company.id
            )
        )
    ).scalar_one()
    developer = (
        await session.execute(select(Developer).where(Developer.id == partnership.developer_id))
    ).scalar_one()
    assert developer.name == "Kolte Patil Developers"

    await session.refresh(company)
    assert company.status == CompanyStatus.ENRICHED.value
    assert company.last_enriched_at is not None
    assert company.year_established == 2010
    # confidence_score is NUMERIC(4,3) -> Decimal on read; pytest.approx bridges
    # the Decimal/float precision gap rather than comparing exact representations.
    assert float(company.confidence_score) == pytest.approx(0.85)

    logs = (
        await session.execute(select(JobLog).where(JobLog.scrape_job_id == job.id))
    ).scalars().all()
    assert any("recorded AI summary" in log.message for log in logs)

    assert extractor.calls[0][0] == "Acme Realty Pune"
    assert "Kothrud" in extractor.calls[0][1]  # assembled content includes crawled markdown


async def test_rerun_versions_summary_and_does_not_duplicate_projections(
    session: AsyncSession, tmp_path
):
    storage = LocalFilesystemObjectStorage(tmp_path)
    company = await _make_enriched_company(session, storage)
    job = await _make_job(session, company)

    await _make_service(FakeAIExtractor(_sample_extraction()), session, storage).run(job)

    job2 = await _make_job(session, company)
    updated_extraction = _sample_extraction(confidence_score=0.95)
    await _make_service(FakeAIExtractor(updated_extraction), session, storage).run(job2)

    summaries = (
        await session.execute(select(AISummary).where(AISummary.company_id == company.id))
    ).scalars().all()
    assert len(summaries) == 2
    current = [s for s in summaries if s.is_current]
    assert len(current) == 1
    assert float(current[0].confidence_score) == pytest.approx(0.95)

    specializations = (
        await session.execute(
            select(CompanySpecialization).where(CompanySpecialization.company_id == company.id)
        )
    ).scalars().all()
    assert len(specializations) == 2  # upserted, not duplicated

    areas = (
        await session.execute(select(ServiceArea).where(ServiceArea.company_id == company.id))
    ).scalars().all()
    assert len(areas) == 2  # upserted, not duplicated


async def test_company_with_no_crawled_content_fails_job(session: AsyncSession, tmp_path):
    storage = LocalFilesystemObjectStorage(tmp_path)
    company = Company(name="No Crawl Co", slug="no-crawl-co-enrichment-test")
    session.add(company)
    await session.flush()
    job = await _make_job(session, company)

    with pytest.raises(ValueError, match="no crawled content"):
        await _make_service(FakeAIExtractor(_sample_extraction()), session, storage).run(job)

    assert job.status == ScrapeJobStatus.FAILED.value
    assert job.error_message is not None


async def test_extractor_failure_marks_job_failed(session: AsyncSession, tmp_path):
    storage = LocalFilesystemObjectStorage(tmp_path)
    company = await _make_enriched_company(session, storage)
    job = await _make_job(session, company)
    extractor = FakeAIExtractor(RuntimeError("provider unavailable"))

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await _make_service(extractor, session, storage).run(job)

    assert job.status == ScrapeJobStatus.FAILED.value
    assert "provider unavailable" in job.error_message
