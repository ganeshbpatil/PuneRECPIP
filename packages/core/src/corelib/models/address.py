import uuid
from typing import TYPE_CHECKING

from geoalchemy2 import Geography
from sqlalchemy import Boolean, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corelib.enums import AddressType
from corelib.models.base import Base
from corelib.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from corelib.models.company import Company


class Address(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "addresses"
    __table_args__ = (
        Index("ix_addresses_company_id", "company_id"),
        Index("ix_addresses_city", "city"),
        Index("ix_addresses_geom", "geom", postgresql_using="gist"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    address_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=AddressType.CORPORATE_OFFICE.value
    )
    line1: Mapped[str | None] = mapped_column(String(500))
    line2: Mapped[str | None] = mapped_column(String(500))
    locality: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(150))
    state: Mapped[str | None] = mapped_column(String(150))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str] = mapped_column(String(100), nullable=False, server_default="India")
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    # Kept in sync with latitude/longitude by the service layer; enables GIST radius
    # / "companies within polygon" queries that plain numeric columns can't index well.
    # spatial_index=False: we declare our own GIST index below (project naming
    # convention) instead of GeoAlchemy2's auto `idx_<table>_<col>` index.
    geom = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    source_url: Mapped[str | None] = mapped_column(String(2048))

    company: Mapped["Company"] = relationship()
