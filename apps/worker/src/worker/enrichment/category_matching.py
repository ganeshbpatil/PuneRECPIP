"""Matches an AI-extracted free-text business category label (e.g. "Real
Estate Broker", "Realty Consultants") against the curated `business_categories`
taxonomy seeded in migration 64d908e31c7b, rather than letting the AI's exact
phrasing create a new row every time. Falls back to creating one only when
nothing close enough already exists — the taxonomy is allowed to grow, but
minor AI phrasing wobble shouldn't fragment it.
"""

import secrets

from corelib.models import BusinessCategory
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from worker.discovery.normalize import slugify

# pg_trgm similarity is 0 (nothing alike) to 1 (identical); 0.4 is a
# deliberately loose bar tuned for short category names like "Broker" vs
# "Real Estate Broker", where token overlap is high but exact match isn't.
SIMILARITY_THRESHOLD = 0.4


async def match_or_create_business_category(
    session: AsyncSession, label: str
) -> BusinessCategory:
    normalized = label.strip()

    exact = (
        await session.execute(
            select(BusinessCategory).where(func.lower(BusinessCategory.name) == normalized.lower())
        )
    ).scalar_one_or_none()
    if exact is not None:
        return exact

    similarity = func.similarity(BusinessCategory.name, normalized)
    closest = (
        await session.execute(
            select(BusinessCategory)
            .where(similarity > SIMILARITY_THRESHOLD)
            .order_by(similarity.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if closest is not None:
        return closest

    return await _create_category(session, normalized)


async def _create_category(session: AsyncSession, name: str) -> BusinessCategory:
    slug = slugify(name)
    for _ in range(5):
        existing = (
            await session.execute(select(BusinessCategory.id).where(BusinessCategory.slug == slug))
        ).scalar_one_or_none()
        if existing is None:
            break
        slug = slugify(name, suffix=secrets.token_hex(3))
    else:
        raise RuntimeError(f"could not generate a unique business_category slug for {name!r}")

    category = BusinessCategory(name=name, slug=slug)
    session.add(category)
    await session.flush()
    return category
