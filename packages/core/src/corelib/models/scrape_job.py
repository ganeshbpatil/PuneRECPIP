import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corelib.enums import ScrapeJobStatus
from corelib.models.base import Base
from corelib.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from corelib.models.company import Company


class ScrapeJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Durable checkpoint/ledger for every pipeline stage (Celery task run), so the
    discovery -> crawl -> extraction -> ... -> indexing pipeline is resumable purely
    from Postgres state even if Redis/Celery state is lost. See docs/architecture."""

    __tablename__ = "scrape_jobs"
    __table_args__ = (
        Index("ix_scrape_jobs_status_type", "status", "job_type"),
        Index("ix_scrape_jobs_company_id", "company_id"),
    )

    job_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=ScrapeJobStatus.PENDING.value
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL")
    )
    parent_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scrape_jobs.id", ondelete="SET NULL")
    )
    queue_name: Mapped[str | None] = mapped_column(String(50))
    payload: Mapped[dict | None] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    checkpoint: Mapped[dict | None] = mapped_column(JSONB)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    company: Mapped["Company | None"] = relationship()
    parent_job: Mapped["ScrapeJob | None"] = relationship(remote_side="ScrapeJob.id")
