import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corelib.models.base import Base
from corelib.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from corelib.models.company import Company


class Contact(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A person at a company (team member). Phone/email for a contact live in the
    shared `phone_numbers`/`emails` tables via `contact_id`, not inline here."""

    __tablename__ = "contacts"
    __table_args__ = (Index("ix_contacts_company_id", "company_id"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    designation: Mapped[str | None] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(150))
    linkedin_url: Mapped[str | None] = mapped_column(String(2048))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    source_url: Mapped[str | None] = mapped_column(String(2048))

    company: Mapped["Company"] = relationship()
