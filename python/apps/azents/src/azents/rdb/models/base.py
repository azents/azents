"""SQLAlchemy base model."""

from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass


class RDBModel(MappedAsDataclass, DeclarativeBase):
    """SQLAlchemy base model.

    Inherits MappedAsDataclass so models can be defined in dataclass style.
    """

    pass
