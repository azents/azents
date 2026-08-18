"""Workspace model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBWorkspace(RDBModel):
    """Workspace table.

    Top-level container for a company or organization.
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
    default_runtime_profile_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey(
            "workspace_runtime_profiles.id",
            name="fk_workspaces_default_runtime_profile_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        default=None,
    )
    default_runtime_profile_version: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=1,
        server_default="1",
    )

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
    CK_DEFAULT_RUNTIME_PROFILE_VERSION_POSITIVE = sa.CheckConstraint(
        "default_runtime_profile_version >= 1",
        name="ck_workspaces_default_runtime_profile_version_positive",
    )
    IX_DEFAULT_RUNTIME_PROFILE_ID = sa.Index(
        "ix_workspaces_default_runtime_profile_id",
        "default_runtime_profile_id",
    )

    __table_args__ = (
        UQ_HANDLE,
        CK_DEFAULT_RUNTIME_PROFILE_VERSION_POSITIVE,
        IX_DEFAULT_RUNTIME_PROFILE_ID,
    )
