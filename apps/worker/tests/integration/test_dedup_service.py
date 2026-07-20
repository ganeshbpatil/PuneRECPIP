"""DedupService against real Postgres — pg_trgm's similarity() scoring the
name-similarity signal, and the real FK/unique constraints on merge_history,
are genuine database features worth exercising for real, same rationale as
test_category_matching.py / test_rera_enrichment_service.py."""

from datetime import UTC, datetime, timedelta

import pytest
from corelib.enums import ChangeSource, CompanyStatus, ScrapeJobStatus, ScrapeJobType
from corelib.models import (
    ChangeHistory,
    Company,
    EmailAddress,
    JobLog,
    MergeHistory,
    PhoneNumber,
    ScrapeJob,
    Website,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from worker.dedup.service import DedupService

pytestmark = pytest.mark.asyncio


async def _make_company(
    session: AsyncSession,
    name: str,
    slug: str,
    *,
    status: str = CompanyStatus.DISCOVERED.value,
    discovered_at: datetime | None = None,
) -> Company:
    company = Company(name=name, slug=slug, status=status, discovered_at=discovered_at)
    session.add(company)
    await session.flush()
    return company


async def _make_job(session: AsyncSession, company: Company) -> ScrapeJob:
    job = ScrapeJob(
        job_type=ScrapeJobType.DEDUP.value,
        status=ScrapeJobStatus.PENDING.value,
        company_id=company.id,
    )
    session.add(job)
    await session.commit()
    return job


async def test_shared_domain_alone_auto_merges(session: AsyncSession):
    a = await _make_company(session, "Acme Realty Pune", "acme-realty-pune-dedup-a")
    b = await _make_company(session, "Acme Realty Pune LLP", "acme-realty-pune-dedup-b")
    session.add(Website(company_id=a.id, url="https://acme.example/", domain="acme.example"))
    session.add(Website(company_id=b.id, url="https://acme.example/contact", domain="acme.example"))
    await session.flush()
    job = await _make_job(session, a)

    result = await DedupService(session).run(job)

    assert job.status == ScrapeJobStatus.SUCCEEDED.value
    assert result["candidates_considered"] == 1
    assert len(result["merges"]) == 1

    await session.refresh(b)
    assert b.status == CompanyStatus.MERGED.value
    assert b.is_duplicate is True
    assert b.merged_into_company_id == a.id

    merge = (
        await session.execute(
            select(MergeHistory).where(MergeHistory.duplicate_company_id == b.id)
        )
    ).scalar_one()
    assert merge.primary_company_id == a.id
    assert merge.match_criteria["domain_match"] is True
    assert float(merge.match_score) >= 0.6

    change = (
        await session.execute(
            select(ChangeHistory).where(
                ChangeHistory.entity_type == "company", ChangeHistory.entity_id == b.id
            )
        )
    ).scalar_one()
    assert change.change_source == ChangeSource.DEDUP_MERGE.value
    assert change.new_value == {"status": "merged"}

    logs = (
        await session.execute(select(JobLog).where(JobLog.scrape_job_id == job.id))
    ).scalars().all()
    assert any("merged duplicate company" in log.message for log in logs)




async def test_shared_phone_alone_does_not_auto_merge(session: AsyncSession):
    a = await _make_company(session, "Kothrud Estates", "kothrud-estates-dedup-a")
    b = await _make_company(session, "Totally Unrelated Business Name", "unrelated-dedup-b")
    session.add(PhoneNumber(company_id=a.id, phone_number="+912012345678"))
    session.add(PhoneNumber(company_id=b.id, phone_number="+912012345678"))
    await session.flush()
    job = await _make_job(session, a)

    result = await DedupService(session).run(job)

    assert result["candidates_considered"] == 1
    assert result["merges"] == []
    await session.refresh(b)
    assert b.status != CompanyStatus.MERGED.value


async def test_shared_email_alone_does_not_auto_merge(session: AsyncSession):
    a = await _make_company(session, "FC Road Realty", "fc-road-realty-dedup-a")
    b = await _make_company(session, "Entirely Different Company", "different-co-dedup-b")
    session.add(EmailAddress(company_id=a.id, email="info@shared-office.example"))
    session.add(EmailAddress(company_id=b.id, email="info@shared-office.example"))
    await session.flush()
    job = await _make_job(session, a)

    result = await DedupService(session).run(job)

    assert result["candidates_considered"] == 1
    assert result["merges"] == []


async def test_phone_plus_name_similarity_crosses_threshold(session: AsyncSession):
    a = await _make_company(session, "Kothrud Estates Pune", "kothrud-estates-plus-a")
    b = await _make_company(session, "Kothrud Estates Pune Pvt Ltd", "kothrud-estates-plus-b")
    session.add(PhoneNumber(company_id=a.id, phone_number="+912012345679"))
    session.add(PhoneNumber(company_id=b.id, phone_number="+912012345679"))
    await session.flush()
    job = await _make_job(session, a)

    result = await DedupService(session).run(job)

    assert len(result["merges"]) == 1


async def test_name_similarity_alone_never_auto_merges(session: AsyncSession):
    a = await _make_company(session, "Sai Balaji Properties", "sai-balaji-properties-dedup-a")
    b = await _make_company(session, "Sai Balaji Properties", "sai-balaji-properties-dedup-b")
    job = await _make_job(session, a)

    result = await DedupService(session).run(job)

    # Identical names, zero shared structural signals -> considered, not merged.
    assert result["candidates_considered"] == 1
    assert result["merges"] == []
    await session.refresh(b)
    assert b.status != CompanyStatus.MERGED.value


async def test_higher_status_candidate_becomes_primary(session: AsyncSession):
    discovered = await _make_company(
        session, "Acme Realty Pune", "acme-status-discovered", status=CompanyStatus.DISCOVERED.value
    )
    enriched = await _make_company(
        session, "Acme Realty Pune", "acme-status-enriched", status=CompanyStatus.ENRICHED.value
    )
    session.add(
        Website(company_id=discovered.id, url="https://acme2.example/", domain="acme2.example")
    )
    session.add(
        Website(company_id=enriched.id, url="https://acme2.example/x", domain="acme2.example")
    )
    await session.flush()
    job = await _make_job(session, discovered)

    result = await DedupService(session).run(job)

    assert result["merges"][0]["primary_company_id"] == str(enriched.id)
    assert result["merges"][0]["duplicate_company_id"] == str(discovered.id)
    await session.refresh(discovered)
    assert discovered.status == CompanyStatus.MERGED.value
    assert discovered.merged_into_company_id == enriched.id


async def test_tie_break_prefers_older_discovered_at(session: AsyncSession):
    now = datetime.now(UTC)
    older = await _make_company(
        session, "Acme Realty Pune", "acme-tie-older", discovered_at=now - timedelta(days=10)
    )
    newer = await _make_company(
        session, "Acme Realty Pune", "acme-tie-newer", discovered_at=now
    )
    session.add(Website(company_id=older.id, url="https://acme3.example/", domain="acme3.example"))
    session.add(Website(company_id=newer.id, url="https://acme3.example/x", domain="acme3.example"))
    await session.flush()
    job = await _make_job(session, newer)

    result = await DedupService(session).run(job)

    assert result["merges"][0]["primary_company_id"] == str(older.id)
    assert result["merges"][0]["duplicate_company_id"] == str(newer.id)


async def test_company_that_becomes_duplicate_stops_evaluating_other_candidates(
    session: AsyncSession,
):
    """`company` (the job's subject) can itself lose the primary slot to a
    higher-status candidate partway through the candidate list. Once that
    happens it's no longer an active listing, so remaining candidates
    shouldn't be evaluated (or merged) against it."""
    subject = await _make_company(
        session, "Acme Realty Pune", "acme-stop-subject", status=CompanyStatus.DISCOVERED.value
    )
    better = await _make_company(
        session, "Acme Realty Pune", "acme-stop-better", status=CompanyStatus.VERIFIED.value
    )
    also_similar = await _make_company(
        session, "Acme Realty Pune", "acme-stop-also", status=CompanyStatus.DISCOVERED.value
    )
    session.add(
        Website(company_id=subject.id, url="https://acme4.example/", domain="acme4.example")
    )
    session.add(
        Website(company_id=better.id, url="https://acme4.example/x", domain="acme4.example")
    )
    session.add(PhoneNumber(company_id=subject.id, phone_number="+912099999999"))
    session.add(PhoneNumber(company_id=also_similar.id, phone_number="+912099999999"))
    await session.flush()
    job = await _make_job(session, subject)

    result = await DedupService(session).run(job)

    assert len(result["merges"]) == 1
    assert result["merges"][0]["duplicate_company_id"] == str(subject.id)
    await session.refresh(also_similar)
    # also_similar shared subject's phone number but was never reached,
    # since subject was merged away on the first (domain) match.
    assert also_similar.status != CompanyStatus.MERGED.value


async def test_already_merged_company_is_skipped(session: AsyncSession):
    company = await _make_company(
        session, "Merged Co", "merged-co-dedup", status=CompanyStatus.MERGED.value
    )
    job = await _make_job(session, company)

    result = await DedupService(session).run(job)

    assert job.status == ScrapeJobStatus.SUCCEEDED.value
    assert result == {"candidates_considered": 0, "merges": []}


async def test_already_merged_candidate_is_excluded(session: AsyncSession):
    a = await _make_company(session, "Excluded Co", "excluded-co-dedup-a")
    merged_elsewhere = await _make_company(
        session, "Excluded Co", "excluded-co-dedup-b", status=CompanyStatus.MERGED.value
    )
    session.add(
        Website(company_id=a.id, url="https://excluded.example/", domain="excluded.example")
    )
    session.add(
        Website(
            company_id=merged_elsewhere.id,
            url="https://excluded.example/x",
            domain="excluded.example",
        )
    )
    await session.flush()
    job = await _make_job(session, a)

    result = await DedupService(session).run(job)

    assert result["candidates_considered"] == 0
    assert result["merges"] == []
