"""WorkspaceInvitation model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import InvitationStatus, WorkspaceUserRole
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _invitation_status_values(status_enum: type[InvitationStatus]) -> list[str]:
    """Return InvitationStatus enum values stored in the DB."""
    return [s.value for s in status_enum]


def _workspace_user_role_values(role_enum: type[WorkspaceUserRole]) -> list[str]:
    """Return WorkspaceUserRole enum values stored in the DB."""
    return [role.value for role in role_enum]


invitation_status_enum = ENUM(
    InvitationStatus,
    name="invitation_status",
    create_type=False,
    values_callable=_invitation_status_values,
)

workspace_user_role_enum = ENUM(
    WorkspaceUserRole,
    name="workspace_user_role",
    create_type=False,
    values_callable=_workspace_user_role_values,
)


class RDBWorkspaceInvitation(RDBModel):
    """WorkspaceInvitation table.

    workspace member invitationt managet.
    email t invite by, join t regardless invitation possiblet.
    """

    __tablename__ = "workspace_invitations"

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
    email: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    role: Mapped[WorkspaceUserRole] = mapped_column(
        workspace_user_role_enum, nullable=False
    )
    invited_by: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspace_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[InvitationStatus] = mapped_column(
        invitation_status_enum,
        nullable=False,
        default=InvitationStatus.PENDING,
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
    UQ_WORKSPACE_EMAIL = sa.UniqueConstraint(
        "workspace_id", "email", name="uq_workspace_invitations_workspace_email"
    )
    IX_EMAIL = sa.Index("ix_workspace_invitations_email", "email")

    __table_args__ = (UQ_WORKSPACE_EMAIL, IX_EMAIL)
