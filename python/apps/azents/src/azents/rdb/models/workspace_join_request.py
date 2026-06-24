"""WorkspaceJoinRequest model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import JoinRequestStatus
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _join_request_status_values(
    status_enum: type[JoinRequestStatus],
) -> list[str]:
    """Return JoinRequestStatus enum values stored in the DB."""
    return [s.value for s in status_enum]


join_request_status_enum = ENUM(
    JoinRequestStatus,
    name="join_request_status",
    create_type=False,
    values_callable=_join_request_status_values,
)


class RDBWorkspaceJoinRequest(RDBModel):
    """WorkspaceJoinRequest table.

    t workspace joint requestt t managet.
    manager/ownert approve/reject/mute processt.
    """

    __tablename__ = "workspace_join_requests"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    message: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    status: Mapped[JoinRequestStatus] = mapped_column(
        join_request_status_enum,
        nullable=False,
        default=JoinRequestStatus.PENDING,
    )
    last_notified_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
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

    # Constraint condition and index.
    UQ_WORKSPACE_USER = sa.UniqueConstraint(
        "workspace_id",
        "user_id",
        name="uq_workspace_join_requests_workspace_user",
    )
    IX_WORKSPACE_ID = sa.Index(
        "ix_workspace_join_requests_workspace_id", "workspace_id"
    )
    IX_USER_ID = sa.Index("ix_workspace_join_requests_user_id", "user_id")

    __table_args__ = (UQ_WORKSPACE_USER, IX_WORKSPACE_ID, IX_USER_ID)
