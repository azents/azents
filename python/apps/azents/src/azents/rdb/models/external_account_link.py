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


class RDBExternalAccountLinkOrigin(RDBModel):
    """Original signed provider actor proof context."""

    __tablename__ = "external_account_link_origins"

    UQ_CONNECTION_INTERACTION = sa.UniqueConstraint(
        "connection_id",
        "provider_interaction_id",
        name="uq_external_account_link_origins_connection_interaction",
    )
    IX_EXPIRES_AT = sa.Index(
        "ix_external_account_link_origins_expires_at",
        "expires_at",
    )
    IX_WORKSPACE_ID = sa.Index(
        "ix_external_account_link_origins_workspace_id",
        "workspace_id",
    )

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
    connection_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    connection_configuration_generation: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
    )
    principal_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_channel_principals.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[ExternalChannelProvider] = mapped_column(
        external_channel_provider_enum,
        nullable=False,
    )
    identity_scope: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    provider_tenant_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    provider_tenant_display_label: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
    )
    provider_user_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    provider_display_label: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
    )
    provider_interaction_id: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
    )
    provider_channel_id: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
    )
    provider_thread_id: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    candidate_count: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    invalid_code_count: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    cancelled_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    consumed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )

    CK_COUNTS_BOUNDED = sa.CheckConstraint(
        "candidate_count >= 0 AND candidate_count <= 5 "
        "AND invalid_code_count >= 0 AND invalid_code_count <= 5",
        name="ck_external_account_link_origins_counts_bounded",
    )

    __table_args__ = (
        UQ_CONNECTION_INTERACTION,
        IX_EXPIRES_AT,
        IX_WORKSPACE_ID,
        CK_COUNTS_BOUNDED,
    )


class RDBExternalAccountLinkCandidate(RDBModel):
    """Immutable elevated browser account candidate."""

    __tablename__ = "external_account_link_candidates"

    UQ_CODE_HASH = sa.UniqueConstraint(
        "code_hash",
        name="uq_external_account_link_candidates_code_hash",
    )
    IX_ORIGIN_ID = sa.Index(
        "ix_external_account_link_candidates_origin_id",
        "origin_id",
    )
    IX_USER_ID = sa.Index(
        "ix_external_account_link_candidates_user_id",
        "user_id",
    )
    IX_EXPIRES_AT = sa.Index(
        "ix_external_account_link_candidates_expires_at",
        "expires_at",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    origin_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_account_link_origins.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    auth_session_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    code_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    provider_proved_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    cancelled_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    consumed_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
    )
    link_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("external_account_links.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        UQ_CODE_HASH,
        IX_ORIGIN_ID,
        IX_USER_ID,
        IX_EXPIRES_AT,
    )
