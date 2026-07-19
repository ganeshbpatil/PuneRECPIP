import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from corelib.models.company import Company

from corelib.models.base import Base
from corelib.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

# Dimension follows OpenAI text-embedding-3-small / Voyage-3-lite class models.
# Bump via migration if the embedding provider changes.
EMBEDDING_DIM = 1536


class AISummary(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """AI-generated structured company profile (Module 5). Historical rows are kept
    with `is_current=false`; only one row per company may have `is_current=true`
    (enforced by a partial unique index), giving a free version history."""

    __tablename__ = "ai_summaries"
    __table_args__ = (
        Index(
            "uq_ai_summaries_company_current",
            "company_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        Index(
            "ix_ai_summaries_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    summary_markdown: Mapped[str | None] = mapped_column(Text)
    structured_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(50))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    confidence_score: Mapped[float | None] = mapped_column(Numeric(4, 3))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    company: Mapped["Company"] = relationship()
