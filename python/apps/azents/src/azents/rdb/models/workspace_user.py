"""WorkspaceUser model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import WorkspaceUserRole
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _workspace_user_role_values(role_enum: type[WorkspaceUserRole]) -> list[str]:
    """Return WorkspaceUserRole enum values stored in the DB."""
    return [role.value for role in role_enum]


workspace_user_role_enum = ENUM(
    WorkspaceUserRole,
    name="workspace_user_role",
    create_type=False,
    values_callable=_workspace_user_role_values,
)


class RDBWorkspaceUser(RDBModel):
    """WorkspaceUser table.

    Workspacet t user profilet.
    Usert connectiont workspacet rolet managet.
    """

    __tablename__ = "workspace_users"

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
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    role: Mapped[WorkspaceUserRole] = mapped_column(
        workspace_user_role_enum, nullable=False
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
        "workspace_id", "user_id", name="uq_workspace_users_workspace_user"
    )
    IX_WORKSPACE_ID = sa.Index("ix_workspace_users_workspace_id", "workspace_id")

    __table_args__ = (UQ_WORKSPACE_USER, IX_WORKSPACE_ID)
