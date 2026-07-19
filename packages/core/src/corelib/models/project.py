import uuid
from typing import TYPE_CHECKING

from geoalchemy2 import Geography
from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corelib.enums import CompanyProjectRole, ProjectStatus, ProjectType
from corelib.models.base import Base
from corelib.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from corelib.models.company import Company
    from corelib.models.developer import Developer


class Project(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_developer_id", "developer_id"),
        Index("ix_projects_city", "city"),
        Index("ix_projects_rera_number", "rera_number"),
        Index("ix_projects_geom", "geom", postgresql_using="gist"),
    )

    developer_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("developers.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    slug: Mapped[str] = mapped_column(String(550), nullable=False)
    project_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=ProjectType.RESIDENTIAL.value
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=ProjectStatus.UNDER_CONSTRUCTION.value
    )
    city: Mapped[str | None] = mapped_column(String(150))
    state: Mapped[str | None] = mapped_column(String(150))
    locality: Mapped[str | None] = mapped_column(String(255))
    pincode: Mapped[str | None] = mapped_column(String(20))
    rera_number: Mapped[str | None] = mapped_column(String(100))
    geom = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True
    )
    source_url: Mapped[str | None] = mapped_column(String(2048))

    developer: Mapped["Developer | None"] = relationship()


class CompanyProject(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Which companies market/sell a given project, and in what capacity."""

    __tablename__ = "company_projects"
    __table_args__ = (
        UniqueConstraint("company_id", "project_id", "role", name="uq_company_project_role"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=CompanyProjectRole.CHANNEL_PARTNER.value
    )
    source_url: Mapped[str | None] = mapped_column(String(2048))

    company: Mapped["Company"] = relationship()
    project: Mapped["Project"] = relationship()
