"""GitHub installations accessible by each user.

Stores the GitHub App installation list discovered through user OAuth.
Used to verify installation_id ownership when registering toolkits.
"""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBGithubUserInstallation(RDBModel):
    """GitHub App installation for each user."""

    __tablename__ = "github_user_installations"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    installation_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
    )
    account_login: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
    )
    account_type: Mapped[str] = mapped_column(
        sa.String(50),
        nullable=False,
    )
    platform_app_id: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
    )
    account_avatar_url: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
        default="",
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

    UQ_USER_APP_INSTALLATION = sa.Index(
        "uq_github_user_installations_user_app_installation",
        "user_id",
        "platform_app_id",
        "installation_id",
        unique=True,
    )
    IX_USER_ID = sa.Index("ix_github_user_installations_user_id", "user_id")
    IX_PLATFORM_APP_ID = sa.Index(
        "ix_github_user_installations_platform_app_id",
        "platform_app_id",
    )

    __table_args__ = (
        UQ_USER_APP_INSTALLATION,
        IX_USER_ID,
        IX_PLATFORM_APP_ID,
    )
