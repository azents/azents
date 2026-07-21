"""User model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBUser(RDBModel):
    """User table.

    User entity.
    Represents a user account independent of workspaces.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    primary_email_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey(
            "user_emails.id",
            use_alter=True,
            name="fk_users_primary_email_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=False,
    )
    locale: Mapped[str] = mapped_column(
        sa.String(35),
        nullable=False,
        server_default="en-US",
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
