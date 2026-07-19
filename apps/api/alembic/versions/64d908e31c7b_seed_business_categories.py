"""seed business categories

Revision ID: 64d908e31c7b
Revises: d3bd343165c9
Create Date: 2026-07-19 18:55:34.411112

Data-only migration: seeds the curated `business_categories` taxonomy Module 5
(AI Enrichment) matches AI-extracted free-text category labels against (see
worker.enrichment.category_matching). Uses a lightweight ad-hoc table()
rather than importing the ORM model directly, per Alembic's own guidance —
migrations should be independent of a model that will keep evolving.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '64d908e31c7b'
down_revision: Union[str, None] = 'd3bd343165c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CATEGORIES = [
    ("Broker", "broker", "Independent agent brokering property sales or leasing on behalf of buyers, sellers, landlords, or tenants."),
    ("Channel Partner", "channel-partner", "Sales/marketing partner empanelled by one or more developers to sell their projects."),
    ("Developer", "developer", "Builds and sells or leases its own real estate projects."),
    ("Consultant", "consultant", "Advisory-focused real estate practice — market analysis, valuation, investment guidance."),
    ("Leasing Firm", "leasing-firm", "Specializes in residential or commercial leasing/rental transactions."),
    ("Property Management Company", "property-management-company", "Manages properties on behalf of owners: maintenance, tenant relations, rent collection."),
    ("Real Estate Agency", "real-estate-agency", "Full-service agency covering sales, leasing, and related services under one brand."),
    ("Investment Advisory", "investment-advisory", "Focused on real estate as an investment/asset class rather than end-user transactions."),
    ("Land Aggregator", "land-aggregator", "Specializes in land parcel identification, aggregation, and sale for development."),
]

business_categories = sa.table(
    "business_categories",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("slug", sa.String),
    sa.column("description", sa.Text),
)


def upgrade() -> None:
    # created_at/updated_at are left out of the payload entirely so each
    # column's own server_default=func.now() applies, rather than trying to
    # pass a SQL expression through bulk_insert's parameter binding.
    op.bulk_insert(
        business_categories,
        [
            {"name": name, "slug": slug, "description": description}
            for name, slug, description in CATEGORIES
        ],
    )


def downgrade() -> None:
    op.execute(
        business_categories.delete().where(
            business_categories.c.slug.in_([slug for _, slug, _ in CATEGORIES])
        )
    )
