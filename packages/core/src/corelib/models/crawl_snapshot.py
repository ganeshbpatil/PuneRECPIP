import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, SmallInteger, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corelib.enums import PageType
from corelib.models.base import Base
from corelib.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from corelib.models.company import Company
    from corelib.models.scrape_job import ScrapeJob
    from corelib.models.website import Website


class CrawlSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One row per crawled page (Module 4). Large artifacts (raw HTML, clean
    HTML, markdown, screenshot) live in object storage per
    docs/architecture/01-architecture.md §5 — only their storage keys are kept
    here, alongside deterministically-extracted structured data (emails,
    phones, internal links) which is small and queryable enough to live in
    JSONB directly rather than as its own object-storage artifact.

    Historical rows are kept with `is_current=false` on re-crawl (same
    `is_current` pattern as `ai_summaries`) so change detection (Module 12) has
    something to diff against; only one row per (company_id, url) may be
    current."""

    __tablename__ = "crawl_snapshots"
    __table_args__ = (
        Index("ix_crawl_snapshots_company_id", "company_id"),
        Index("ix_crawl_snapshots_content_hash", "content_hash"),
        Index(
            "uq_crawl_snapshots_company_url_current",
            "company_id",
            "url",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    scrape_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scrape_jobs.id", ondelete="SET NULL")
    )
    website_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("websites.id", ondelete="SET NULL")
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    page_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=PageType.OTHER.value
    )
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    raw_html_key: Mapped[str | None] = mapped_column(String(500))
    clean_html_key: Mapped[str | None] = mapped_column(String(500))
    markdown_key: Mapped[str | None] = mapped_column(String(500))
    screenshot_key: Mapped[str | None] = mapped_column(String(500))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    extracted_emails: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    extracted_phones: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    extracted_links: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    company: Mapped["Company"] = relationship()
    scrape_job: Mapped["ScrapeJob | None"] = relationship()
    website: Mapped["Website | None"] = relationship()
