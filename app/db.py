from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Basisklasse voor alle ORM-modellen; Alembic gebruikt Base.metadata."""
