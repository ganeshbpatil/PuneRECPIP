import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corelib.enums import CompanyStatus
from corelib.models.base import Base
from corelib.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from corelib.models.business_category import BusinessCategory


class Company(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Central entity. Everything else (contacts, addresses, websites, scores,
    summaries, service areas, ...) hangs off `company_id`."""

    __tablename__ = "companies"
    __table_args__ = (
        Index("ix_companies_status", "status"),
        Index("ix_companies_last_crawled_at", "last_crawled_at"),
        Index(
            "ix_companies_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    name: Mapped[str] = mapped_column(String(500), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(500))
    slug: Mapped[str] = mapped_column(String(550), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=CompanyStatus.DISCOVERED.value
    )
    year_established: Mapped[int | None] = mapped_column(SmallInteger)
    description: Mapped[str | None] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(String(2048))
    employee_count_range: Mapped[str | None] = mapped_column(String(50))
    confidence_score: Mapped[float | None] = mapped_column(Numeric(4, 3))
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    merged_into_company_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL")
    )
    discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    merged_into: Mapped["Company | None"] = relationship(
        remote_side="Company.id", foreign_keys=[merged_into_company_id]
    )
    categories: Mapped[list["CompanyCategory"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class CompanyCategory(Base):
    """Many-to-many: a company can span more than one business category
    (e.g. Broker + Property Management Company), with one marked primary."""

    __tablename__ = "company_categories"

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("business_categories.id", ondelete="CASCADE"), primary_key=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    company: Mapped["Company"] = relationship(back_populates="categories")
    category: Mapped["BusinessCategory"] = relationship()
