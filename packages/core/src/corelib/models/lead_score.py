import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from corelib.models.company import Company

from corelib.models.base import Base
from corelib.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class LeadScore(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Scored history (Module 10). Latest score per company is the row with the
    greatest `computed_at`, retrieved via the `(company_id, computed_at)` index —
    no `is_current` flag needed since every scoring run is a meaningful data point."""

    __tablename__ = "lead_scores"
    __table_args__ = (Index("ix_lead_scores_company_computed", "company_id", "computed_at"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    website_completeness_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    digital_presence_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    business_maturity_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    service_breadth_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    geographic_coverage_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    review_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    scoring_version: Mapped[str] = mapped_column(String(50), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    company: Mapped["Company"] = relationship()
