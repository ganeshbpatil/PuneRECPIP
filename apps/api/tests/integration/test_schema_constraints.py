import uuid

import pytest
from corelib.enums import CompanyStatus, EmailType, PhoneType
from corelib.models import AISummary, Company, EmailAddress, PhoneNumber, Website
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _make_company(session: AsyncSession, **overrides) -> Company:
    defaults = dict(
        name="Acme Realty Pune",
        slug=f"acme-realty-{uuid.uuid4().hex[:8]}",
        status=CompanyStatus.DISCOVERED.value,
    )
    company = Company(**{**defaults, **overrides})
    session.add(company)
    await session.flush()
    return company


async def test_company_roundtrip_with_website(session: AsyncSession):
    company = await _make_company(session)
    session.add(Website(company_id=company.id, url="https://acme.example", domain="acme.example"))
    await session.flush()

    fetched = (
        await session.execute(select(Company).where(Company.id == company.id))
    ).scalar_one()
    assert fetched.name == "Acme Realty Pune"
    assert fetched.status == CompanyStatus.DISCOVERED.value


async def test_deleting_company_cascades_to_websites(session: AsyncSession):
    company = await _make_company(session)
    session.add(Website(company_id=company.id, url="https://acme.example", domain="acme.example"))
    await session.flush()

    await session.delete(company)
    await session.flush()

    remaining = (
        await session.execute(select(Website).where(Website.company_id == company.id))
    ).scalars().all()
    assert remaining == []


async def test_phone_number_requires_exactly_one_owner(session: AsyncSession):
    company = await _make_company(session)
    # Neither company_id nor contact_id set — violates the owner_xor check constraint.
    session.add(PhoneNumber(phone_number="+919999999999", phone_type=PhoneType.MOBILE.value))
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()

    # Both set — also violates it.
    session.add(
        PhoneNumber(
            company_id=company.id,
            contact_id=uuid.uuid4(),
            phone_number="+919999999999",
            phone_type=PhoneType.MOBILE.value,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_email_owner_xor_allows_company_only(session: AsyncSession):
    company = await _make_company(session)
    session.add(
        EmailAddress(
            company_id=company.id, email="sales@acme.example", email_type=EmailType.SALES.value
        )
    )
    await session.flush()  # no error


async def test_only_one_current_ai_summary_per_company(session: AsyncSession):
    company = await _make_company(session)
    session.add(
        AISummary(
            company_id=company.id,
            structured_json={"business_category": "broker"},
            model_name="claude-sonnet-5",
            is_current=True,
        )
    )
    await session.flush()

    session.add(
        AISummary(
            company_id=company.id,
            structured_json={"business_category": "broker"},
            model_name="claude-sonnet-5",
            is_current=True,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_company_slug_is_unique(session: AsyncSession):
    slug = f"dup-slug-{uuid.uuid4().hex[:8]}"
    await _make_company(session, slug=slug)
    with pytest.raises(IntegrityError):
        await _make_company(session, name="Another Co", slug=slug)
