"""Toolkit model."""

import datetime
import enum
from typing import Any

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import MCPOAuthConnectionStatus
from azents.core.toolkit_ownership import PersonalToolkitAccessMode, ToolkitOwnerKind
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return enum values stored in the DB."""
    return [v.value for v in enum_cls]


mcp_oauth_connection_status_enum = ENUM(
    MCPOAuthConnectionStatus,
    name="mcp_oauth_connection_status",
    create_type=False,
    values_callable=_enum_values,
)


personal_toolkit_access_mode_enum = ENUM(
    PersonalToolkitAccessMode,
    name="personal_toolkit_access_mode",
    create_type=False,
    values_callable=_enum_values,
)
toolkit_owner_kind_enum = ENUM(
    ToolkitOwnerKind,
    name="toolkit_owner_kind",
    create_type=False,
    values_callable=_enum_values,
)


class RDBToolkitConfig(RDBModel):
    """ToolkitConfig table.

    A manager-created tool and settings bundle. Multiple agents can share the
    same ToolkitConfig.
    """

    __tablename__ = "toolkit_configs"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    owner_kind: Mapped[ToolkitOwnerKind] = mapped_column(
        toolkit_owner_kind_enum, nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_agent_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=True,
    )
    owner_user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey(
            "users.id", ondelete="CASCADE", name="fk_toolkit_configs_owner_user_id"
        ),
        nullable=True,
    )
    personal_access_mode: Mapped[PersonalToolkitAccessMode | None] = mapped_column(
        personal_toolkit_access_mode_enum,
        nullable=True,
    )
    toolkit_type: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    slug: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, default=None
    )
    prompt: Mapped[str | None] = mapped_column(sa.Text, nullable=True, default=None)
    encrypted_credentials: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, default=None
    )
    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    always_expose_tools: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=False,
        server_default=sa.false(),
    )
    revision: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        default=1,
        server_default=sa.text("1"),
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

    IX_WORKSPACE_ID = sa.Index("ix_toolkit_configs_workspace_id", "workspace_id")
    IX_OWNER_AGENT_ID = sa.Index(
        "ix_toolkit_configs_owner_agent_id",
        "owner_agent_id",
    )
    IX_OWNER_USER_ID = sa.Index("ix_toolkit_configs_owner_user_id", "owner_user_id")
    CK_OWNER_SHAPE = sa.CheckConstraint(
        "(owner_kind = 'workspace' AND workspace_id IS NOT NULL "
        "AND owner_agent_id IS NULL AND owner_user_id IS NULL "
        "AND personal_access_mode IS NULL) OR "
        "(owner_kind = 'agent' AND workspace_id IS NOT NULL "
        "AND owner_agent_id IS NOT NULL AND owner_user_id IS NULL "
        "AND personal_access_mode IS NULL) OR "
        "(owner_kind = 'user' AND workspace_id IS NOT NULL AND owner_agent_id IS NULL "
        "AND owner_user_id IS NOT NULL AND personal_access_mode IS NOT NULL)",
        name="ck_toolkit_configs_owner_shape",
    )
    UQ_ID_OWNER_USER = sa.UniqueConstraint(
        "id", "owner_user_id", "workspace_id", name="uq_toolkit_configs_id_owner_user"
    )

    __table_args__ = (
        IX_WORKSPACE_ID,
        IX_OWNER_AGENT_ID,
        IX_OWNER_USER_ID,
        CK_OWNER_SHAPE,
        UQ_ID_OWNER_USER,
    )


class RDBPersonalToolkitAgent(RDBModel):
    """Positive Selected-mode membership, independent of shared attachments."""

    __tablename__ = "personal_toolkit_agents"

    toolkit_id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
    )
    owner_user_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    workspace_id: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
    )
    IX_AGENT_ID = sa.Index("ix_personal_toolkit_agents_agent_id", "agent_id")
    FK_PERSONAL_OWNER = sa.ForeignKeyConstraint(
        ["toolkit_id", "owner_user_id", "workspace_id"],
        [
            "toolkit_configs.id",
            "toolkit_configs.owner_user_id",
            "toolkit_configs.workspace_id",
        ],
        ondelete="CASCADE",
        name="fk_personal_toolkit_agents_owner",
    )
    FK_AGENT_WORKSPACE = sa.ForeignKeyConstraint(
        ["agent_id", "workspace_id"],
        ["agents.id", "agents.workspace_id"],
        ondelete="CASCADE",
        name="fk_personal_toolkit_agents_agent_workspace",
    )
    __table_args__ = (IX_AGENT_ID, FK_PERSONAL_OWNER, FK_AGENT_WORKSPACE)


class RDBAgentToolkit(RDBModel):
    """AgentToolkit table.

    Toolkit attached to an Agent. Each Agent can attach a Toolkit only once.
    """

    __tablename__ = "agent_toolkits"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    toolkit_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("toolkit_configs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Denormalized toolkit type for one-tool-per-agent constraints.
    toolkit_type: Mapped[str] = mapped_column(sa.String(100), nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
    )

    UQ_AGENT_TOOLKIT = sa.UniqueConstraint(
        "agent_id",
        "toolkit_id",
        name="uq_agent_toolkits_agent_toolkit",
    )
    IX_AGENT_ID = sa.Index("ix_agent_toolkits_agent_id", "agent_id")

    __table_args__ = (UQ_AGENT_TOOLKIT, IX_AGENT_ID)


class RDBAgentToolkitNamespaceReservation(RDBModel):
    """Durable Agent-local namespace allocation for one ToolkitConfig."""

    __tablename__ = "agent_toolkit_namespace_reservations"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    toolkit_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("toolkit_configs.id", ondelete="SET NULL"),
        nullable=True,
    )
    base_slug: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    ordinal: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    namespace: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
    )

    UQ_AGENT_NAMESPACE = sa.UniqueConstraint(
        "agent_id",
        "namespace",
        name="uq_agent_toolkit_namespace_reservations_agent_namespace",
    )
    UQ_AGENT_BASE_ORDINAL = sa.UniqueConstraint(
        "agent_id",
        "base_slug",
        "ordinal",
        name="uq_agent_toolkit_namespace_reservations_agent_base_ordinal",
    )
    CK_ORDINAL_POSITIVE = sa.CheckConstraint(
        "ordinal >= 1",
        name="ck_agent_toolkit_namespace_reservations_ordinal_positive",
    )
    UQ_ACTIVE_AGENT_TOOLKIT = sa.Index(
        "ix_agent_toolkit_namespace_reservations_agent_id_toolkit_id",
        "agent_id",
        "toolkit_id",
        unique=True,
        postgresql_where=sa.text("toolkit_id IS NOT NULL"),
    )
    IX_TOOLKIT_ID = sa.Index(
        "ix_agent_toolkit_namespace_reservations_toolkit_id",
        "toolkit_id",
    )

    __table_args__ = (
        UQ_AGENT_NAMESPACE,
        UQ_AGENT_BASE_ORDINAL,
        CK_ORDINAL_POSITIVE,
        UQ_ACTIVE_AGENT_TOOLKIT,
        IX_TOOLKIT_ID,
    )


class RDBAgentToolkitNamespaceSequence(RDBModel):
    """Highest consumed namespace ordinal for one Agent and base Slug."""

    __tablename__ = "agent_toolkit_namespace_sequences"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    base_slug: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    last_ordinal: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
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

    UQ_AGENT_BASE = sa.UniqueConstraint(
        "agent_id",
        "base_slug",
        name="uq_agent_toolkit_namespace_sequences_agent_base",
    )
    CK_LAST_ORDINAL_NONNEGATIVE = sa.CheckConstraint(
        "last_ordinal >= 0",
        name="ck_agent_toolkit_namespace_sequences_last_ordinal_nonnegative",
    )

    __table_args__ = (UQ_AGENT_BASE, CK_LAST_ORDINAL_NONNEGATIVE)


class RDBMCPOAuthConnection(RDBModel):
    """MCPOAuthConnection table.

    Stores toolkit-level MCP OAuth client registration and token state. Only one
    OAuth connection is allowed for each ToolkitConfig.
    """

    __tablename__ = "mcp_oauth_connections"

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    toolkit_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("toolkit_configs.id", ondelete="CASCADE"),
        nullable=False,
    )
    server_url: Mapped[str] = mapped_column(sa.Text, nullable=False)
    authorization_endpoint: Mapped[str] = mapped_column(sa.Text, nullable=False)
    token_endpoint: Mapped[str] = mapped_column(sa.Text, nullable=False)
    encrypted_client_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    issuer: Mapped[str | None] = mapped_column(sa.Text, nullable=True, default=None)
    resource: Mapped[str | None] = mapped_column(sa.Text, nullable=True, default=None)
    registration_endpoint: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, default=None
    )
    encrypted_client_secret: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, default=None
    )
    token_endpoint_auth_method: Mapped[str] = mapped_column(
        sa.String(64), nullable=False, default="client_secret_post"
    )
    scope: Mapped[str | None] = mapped_column(sa.Text, nullable=True, default=None)
    encrypted_access_token: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, default=None
    )
    encrypted_refresh_token: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, default=None
    )
    expires_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime, nullable=True, default=None
    )
    status: Mapped[MCPOAuthConnectionStatus] = mapped_column(
        mcp_oauth_connection_status_enum,
        nullable=False,
        default=MCPOAuthConnectionStatus.CONNECTED,
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

    UQ_TOOLKIT = sa.UniqueConstraint(
        "toolkit_id", name="uq_mcp_oauth_connections_toolkit_id"
    )
    IX_TOOLKIT_ID = sa.Index("ix_mcp_oauth_connections_toolkit_id", "toolkit_id")

    __table_args__ = (UQ_TOOLKIT, IX_TOOLKIT_ID)
