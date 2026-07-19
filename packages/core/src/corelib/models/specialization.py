import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corelib.enums import DataSource
from corelib.models.base import Base
from corelib.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from corelib.models.company import Company


class CompanySpecialization(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One row per property-type flag a company is extracted/marked as active in
    (residential sales, commercial leasing, luxury, industrial, ...). Normalized
    instead of a dozen boolean columns on `companies` so it stays filterable/indexable
    as new specializations are added and so each flag carries its own confidence."""

    __tablename__ = "company_specializations"
    __table_args__ = (
        UniqueConstraint("company_id", "specialization", name="uq_company_specialization"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    specialization: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    confidence_score: Mapped[float | None] = mapped_column(Numeric(4, 3))
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=DataSource.AI_EXTRACTION.value
    )

    company: Mapped["Company"] = relationship()
