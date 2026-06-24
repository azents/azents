"""Workspace model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBWorkspace(RDBModel):
    """Workspace table.

    company/organization unitt top-level containert.
    """

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    handle: Mapped[str] = mapped_column(sa.String(255), nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    # Constraint condition.
    UQ_HANDLE = sa.UniqueConstraint("handle", name="uq_workspaces_handle")

    __table_args__ = (UQ_HANDLE,)
