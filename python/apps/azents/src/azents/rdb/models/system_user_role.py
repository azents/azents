"""Instance-wide User role and bootstrap state models."""

import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import SystemUserRole
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime

system_user_role_enum = ENUM(
    SystemUserRole,
    name="system_user_role",
    create_type=False,
    values_callable=lambda role_enum: [role.value for role in role_enum],
)


class RDBSystemUserRole(RDBModel):
    """Instance-wide User role assignment table."""

    __tablename__ = "system_user_roles"

    user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[SystemUserRole] = mapped_column(
        system_user_role_enum,
        primary_key=True,
    )
    granted_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )
    granted_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
    )

    IX_ROLE = sa.Index("ix_system_user_roles_role", "role")
    IX_GRANTED_BY_USER_ID = sa.Index(
        "ix_system_user_roles_granted_by_user_id",
        "granted_by_user_id",
    )

    __table_args__ = (IX_ROLE, IX_GRANTED_BY_USER_ID)


class RDBSystemBootstrapState(RDBModel):
    """Singleton initial instance bootstrap state."""

    __tablename__ = "system_bootstrap_states"

    id: Mapped[int] = mapped_column(
        sa.Integer,
        primary_key=True,
        init=False,
        default=1,
    )
    token_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
    )
    consumed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        default=None,
    )

    CK_SINGLETON_ID = sa.CheckConstraint(
        "id = 1",
        name="ck_system_bootstrap_states_singleton_id",
    )

    __table_args__ = (CK_SINGLETON_ID,)
