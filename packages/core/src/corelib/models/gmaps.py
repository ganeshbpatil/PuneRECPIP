import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from geoalchemy2 import Geography
from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from corelib.models.company import Company

from corelib.models.base import Base
from corelib.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class GoogleMapsListing(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "google_maps_listings"
    __table_args__ = (
        Index("ix_google_maps_listings_company_id", "company_id"),
        Index("ix_google_maps_listings_geom", "geom", postgresql_using="gist"),
    )

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL")
    )
    place_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    listing_name: Mapped[str | None] = mapped_column(String(500))
    category: Mapped[str | None] = mapped_column(String(150))
    rating: Mapped[float | None] = mapped_column(Numeric(2, 1))
    review_count: Mapped[int | None] = mapped_column(Integer)
    formatted_address: Mapped[str | None] = mapped_column(String(1000))
    geom = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True
    )
    phone: Mapped[str | None] = mapped_column(String(32))
    website_url: Mapped[str | None] = mapped_column(String(2048))
    opening_hours: Mapped[dict | None] = mapped_column(JSONB)
    price_level: Mapped[int | None] = mapped_column(SmallInteger)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    company: Mapped["Company | None"] = relationship()
