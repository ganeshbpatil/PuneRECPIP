"""Against real Postgres — pg_trgm's `similarity()` is a real database
feature, not something a fake/mock can meaningfully stand in for."""

import pytest
from corelib.models import BusinessCategory
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from worker.enrichment.category_matching import match_or_create_business_category

pytestmark = pytest.mark.asyncio


async def test_exact_match_case_insensitive(session: AsyncSession):
    category = await match_or_create_business_category(session, "broker")
    assert category.name == "Broker"
    assert category.slug == "broker"


async def test_fuzzy_match_against_seeded_taxonomy(session: AsyncSession):
    # "Realty Consultants" has no exact match but is close enough (pg_trgm
    # similarity ~0.5) to the seeded "Consultant" row to reuse it.
    category = await match_or_create_business_category(session, "Realty Consultants")
    assert category.name == "Consultant"


async def test_creates_new_category_when_nothing_close_enough(session: AsyncSession):
    category = await match_or_create_business_category(session, "Interior Design Studio")

    assert category.name == "Interior Design Studio"
    assert category.id is not None

    stored = (
        await session.execute(
            select(BusinessCategory).where(BusinessCategory.name == "Interior Design Studio")
        )
    ).scalar_one()
    assert stored.id == category.id


async def test_repeated_label_reuses_the_created_category_not_duplicated(session: AsyncSession):
    label = "Vastu Shastra Consultancy Services"
    first = await match_or_create_business_category(session, label)
    second = await match_or_create_business_category(session, label)

    assert first.id == second.id

    count = (
        await session.execute(select(BusinessCategory).where(BusinessCategory.name == label))
    ).scalars().all()
    assert len(count) == 1
