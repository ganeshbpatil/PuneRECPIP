from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Deterministic constraint/index names so Alembic autogenerate produces stable,
# reviewable diffs instead of Postgres's auto-picked names drifting between runs.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Shared declarative base. Every model in `corelib.models` must inherit from this
    so that a single `Base.metadata` drives Alembic autogeneration."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
