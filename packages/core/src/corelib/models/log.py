import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corelib.enums import LogLevel
from corelib.models.base import Base
from corelib.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from corelib.models.scrape_job import ScrapeJob


class JobLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Structured, queryable log lines tied to a scrape job, surfaced in the admin
    UI. Complements (does not replace) file/stdout logging shipped to Prometheus/
    Sentry per docs/architecture/01-architecture.md §7."""

    __tablename__ = "logs"
    __table_args__ = (
        Index("ix_logs_scrape_job_id", "scrape_job_id"),
        Index("ix_logs_level_created_at", "level", "created_at"),
    )

    scrape_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scrape_jobs.id", ondelete="CASCADE")
    )
    level: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=LogLevel.INFO.value
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict | None] = mapped_column(JSONB)

    scrape_job: Mapped["ScrapeJob | None"] = relationship()
