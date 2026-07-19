"""Matches an AI-extracted developer name against existing `developers` rows.
Exact (case-insensitive, slug-normalized) match only — unlike business
categories, developer names are not a small curated taxonomy but an
organically-growing list of hundreds of real, similarly-named companies
("Kolte Patil" vs "Kolte Constructions"); fuzzy matching here risks silently
merging two distinct developers. Real near-duplicate cleanup is Module 8's
job, same as for companies (see worker.discovery.service's dedup docstring).
"""

import secrets

from corelib.models import Developer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from worker.discovery.normalize import slugify


async def match_or_create_developer(session: AsyncSession, name: str) -> Developer:
    normalized = name.strip()
    slug = slugify(normalized)

    existing = (
        await session.execute(select(Developer).where(Developer.slug == slug))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    for _ in range(5):
        collision = (
            await session.execute(select(Developer.id).where(Developer.slug == slug))
        ).scalar_one_or_none()
        if collision is None:
            break
        slug = slugify(normalized, suffix=secrets.token_hex(3))
    else:
        raise RuntimeError(f"could not generate a unique developer slug for {name!r}")

    developer = Developer(name=normalized, slug=slug)
    session.add(developer)
    await session.flush()
    return developer
