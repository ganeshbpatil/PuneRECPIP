import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corelib.enums import RERARegistrantType, RERAStatus
from corelib.models.base import Base
from corelib.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from corelib.models.company import Company


class RERADetail(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Maharashtra RERA agent/promoter registration matched against a company
    (Module 7). `company_id` is nullable — a registry record can exist before
    (or without) being matched to a discovered company."""

    __tablename__ = "rera_details"
    __table_args__ = (
        Index(
            "ix_rera_details_registrant_name_trgm",
            "registrant_name",
            postgresql_using="gin",
            postgresql_ops={"registrant_name": "gin_trgm_ops"},
        ),
    )

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL")
    )
    registration_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    registrant_name: Mapped[str] = mapped_column(String(500), nullable=False)
    registrant_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=RERARegistrantType.AGENT.value
    )
    registered_address: Mapped[str | None] = mapped_column(Text)
    registration_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=RERAStatus.ACTIVE.value
    )
    source_url: Mapped[str | None] = mapped_column(String(2048))
    matched_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    raw_data: Mapped[dict | None] = mapped_column(JSONB)

    company: Mapped["Company | None"] = relationship()
