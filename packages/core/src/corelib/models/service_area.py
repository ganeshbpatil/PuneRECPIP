import uuid
from typing import TYPE_CHECKING

from geoalchemy2 import Geography
from sqlalchemy import ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corelib.enums import DataSource, ServiceAreaType
from corelib.models.base import Base
from corelib.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from corelib.models.company import Company


class ServiceArea(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Areas/cities/zones/neighbourhoods a company serves (Module 9 — Geographic
    Intelligence). `city`/`state` are plain filters usable Pune-only today and
    India-wide later without a schema change; `geom` is optional for zone polygons."""

    __tablename__ = "service_areas"
    __table_args__ = (
        Index("ix_service_areas_company_id", "company_id"),
        Index("ix_service_areas_city", "city"),
        Index("ix_service_areas_geom", "geom", postgresql_using="gist"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    area_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=ServiceAreaType.CITY.value
    )
    city: Mapped[str | None] = mapped_column(String(150))
    state: Mapped[str | None] = mapped_column(String(150))
    locality: Mapped[str | None] = mapped_column(String(255))
    pincode: Mapped[str | None] = mapped_column(String(20))
    geom = mapped_column(
        Geography(geometry_type="GEOMETRY", srid=4326, spatial_index=False), nullable=True
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=DataSource.AI_EXTRACTION.value
    )
    confidence_score: Mapped[float | None] = mapped_column(Numeric(4, 3))

    company: Mapped["Company"] = relationship()
