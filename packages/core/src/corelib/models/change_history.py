import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corelib.enums import ChangeSource
from corelib.models.base import Base
from corelib.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from corelib.models.scrape_job import ScrapeJob
    from corelib.models.user import User


class ChangeHistory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Generic, append-only, field-level audit trail across every entity type
    (`entity_type` + `entity_id`), independent of Postgres WAL and of `audit_logs`
    (which tracks API actor actions, not data provenance)."""

    __tablename__ = "change_history"
    __table_args__ = (
        Index("ix_change_history_entity", "entity_type", "entity_id", "created_at"),
    )

    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    new_value: Mapped[dict | None] = mapped_column(JSONB)
    change_source: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=ChangeSource.SYSTEM.value
    )
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    changed_by_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("scrape_jobs.id", ondelete="SET NULL")
    )

    changed_by_user: Mapped["User | None"] = relationship()
    changed_by_job: Mapped["ScrapeJob | None"] = relationship()
