import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corelib.enums import EmailType
from corelib.models.base import Base
from corelib.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from corelib.models.company import Company
    from corelib.models.contact import Contact


class EmailAddress(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Owned by exactly one of `company` or `contact` (never both, never neither)."""

    __tablename__ = "emails"
    __table_args__ = (
        CheckConstraint(
            "(company_id IS NOT NULL AND contact_id IS NULL) "
            "OR (company_id IS NULL AND contact_id IS NOT NULL)",
            # SQLAlchemy's naming convention re-prefixes CheckConstraint names with
            # "ck_<table>_", so the raw name here must NOT already include that prefix.
            name="owner_xor",
        ),
        Index("ix_emails_email", "email"),
        Index("ix_emails_company_id", "company_id"),
        Index("ix_emails_contact_id", "contact_id"),
    )

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE")
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE")
    )
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    email_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=EmailType.GENERAL.value
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    source_url: Mapped[str | None] = mapped_column(String(2048))

    company: Mapped["Company | None"] = relationship()
    contact: Mapped["Contact | None"] = relationship()
