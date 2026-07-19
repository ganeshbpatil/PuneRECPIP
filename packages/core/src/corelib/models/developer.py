import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Numeric, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corelib.enums import DeveloperPartnershipType
from corelib.models.base import Base
from corelib.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from corelib.models.company import Company


class Developer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "developers"

    name: Mapped[str] = mapped_column(String(500), nullable=False)
    slug: Mapped[str] = mapped_column(String(550), unique=True, nullable=False)
    website_url: Mapped[str | None] = mapped_column(String(2048))
    description: Mapped[str | None] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(String(2048))
    headquarters_city: Mapped[str | None] = mapped_column(String(150))
    headquarters_state: Mapped[str | None] = mapped_column(String(150))
    established_year: Mapped[int | None] = mapped_column(SmallInteger)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class CompanyDeveloperPartnership(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Which companies (brokers/channel partners) represent which developers."""

    __tablename__ = "company_developer_partnerships"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "developer_id",
            "relationship_type",
            name="uq_company_developer_relationship",
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    developer_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("developers.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=DeveloperPartnershipType.CHANNEL_PARTNER.value,
    )
    source_url: Mapped[str | None] = mapped_column(String(2048))
    confidence_score: Mapped[float | None] = mapped_column(Numeric(4, 3))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    company: Mapped["Company"] = relationship()
    developer: Mapped["Developer"] = relationship()
