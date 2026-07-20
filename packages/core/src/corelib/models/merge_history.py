import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corelib.models.base import Base
from corelib.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from corelib.models.company import Company
    from corelib.models.scrape_job import ScrapeJob
    from corelib.models.user import User


class MergeHistory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Duplicate-detection merge record (Module 8). Companies are never hard-deleted
    on merge — `duplicate_company_id` is marked `status=merged` and kept for audit,
    so both FKs use RESTRICT rather than CASCADE."""

    __tablename__ = "merge_history"
    __table_args__ = (Index("ix_merge_history_primary_company_id", "primary_company_id"),)

    primary_company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    duplicate_company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    match_score: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    match_criteria: Mapped[dict] = mapped_column(JSONB, nullable=False)
    merged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    merged_by_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scrape_jobs.id", ondelete="SET NULL")
    )

    primary_company: Mapped["Company"] = relationship(foreign_keys=[primary_company_id])
    duplicate_company: Mapped["Company"] = relationship(foreign_keys=[duplicate_company_id])
    merged_by_user: Mapped["User | None"] = relationship()
    merged_by_job: Mapped["ScrapeJob | None"] = relationship()
