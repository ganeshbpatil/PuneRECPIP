from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from corelib.models.base import Base
from corelib.models.mixins import TimestampMixin


class BusinessCategory(Base, TimestampMixin):
    """Broker, Channel Partner, Developer, Consultant, Leasing Firm,
    Property Management Company, ... — hierarchical, small lookup table."""

    __tablename__ = "business_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("business_categories.id", ondelete="SET NULL")
    )

    parent: Mapped["BusinessCategory | None"] = relationship(
        remote_side="BusinessCategory.id", back_populates="children"
    )
    children: Mapped[list["BusinessCategory"]] = relationship(back_populates="parent")
