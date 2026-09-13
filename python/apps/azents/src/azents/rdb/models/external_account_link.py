"""External account linking persistence models."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column, synonym

from azents.core.enums import ExternalChannelProvider
from azents.core.external_account_link import ExternalAccountLinkRevocationReason
from azents.rdb.models.base import RDBModel
from azents.rdb.models.external_channel import external_channel_provider_enum
from azents.rdb.types.datetime import TimeZoneDateTime

external_account_link_revocation_reason_enum = ENUM(
    ExternalAccountLinkRevocationReason,
    name="external_account_link_revocation_reason",
    create_type=False,
    values_callable=lambda values: [value.value for value in values],
)


class RDBExternalAccountLink(RDBModel):
    """Terminally revocable global external identity ownership."""

    __tablename__ = "external_account_links"

    UQ_ACTIVE_EXTERNAL_IDENTITY = sa.Index(
        "uq_external_account_links_active_external_identity",
        "provider",
        "identity_scope",
        "provider_user_id",
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    IX_USER_ID = sa.Index("ix_external_account_links_user_id", "user_id")
    IX_LEGACY_WORKSPACE_ID = sa.Index(
        "ix_external_account_links_legacy_workspace_id",
        "legacy_workspace_id",
    )

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
    provider: Mapped[ExternalChannelProvider] = mapped_column(
        external_channel_provider_enum,
        nullable=False,
    )
    identity_scope: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    provider_tenant_display_label: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
    )
    provider_display_label: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
    )
    linked_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    legacy_workspace_id: Mapped[str | None] = mapped_column(
        "legacy_workspace_id",
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
        kw_only=True,
    )
    workspace_id: Mapped[str | None] = synonym(
        "legacy_workspace_id",
        init=True,
        default=None,
        kw_only=True,
    )
    revocation_reason: Mapped[ExternalAccountLinkRevocationReason | None] = (
        mapped_column(
            external_account_link_revocation_reason_enum,
            nullable=True,
            default=None,
            kw_only=True,
        )
    )

    __table_args__ = (
        UQ_ACTIVE_EXTERNAL_IDENTITY,
        IX_USER_ID,
        IX_LEGACY_WORKSPACE_ID,
    )
