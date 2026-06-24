"""Agent model."""

import datetime
from typing import Any

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import AgentRole, AgentType
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _agent_type_values(enum_cls: type[AgentType]) -> list[str]:
    """Return AgentType enum values stored in the DB."""
    return [v.value for v in enum_cls]


agent_type_enum = ENUM(
    AgentType,
    name="agent_type",
    create_type=False,
    values_callable=_agent_type_values,
)


def _agent_role_values(enum_cls: type[AgentRole]) -> list[str]:
    """Return AgentRole enum values stored in the DB."""
    return [v.value for v in enum_cls]


agent_role_enum = ENUM(
    AgentRole,
    name="agent_role",
    create_type=False,
    values_callable=_agent_role_values,
)


class RDBAgent(RDBModel):
    """Agent table.

    Workspace-scoped settings for LLM model, parameters, and system prompt.
    """

    __tablename__ = "agents"

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
    name: Mapped[str] = mapped_column(sa.String(100), nullable=False)

    model_selection: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    lightweight_model_selection: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )

    # Optional field. Defaults are required only when explicitly needed.
    description: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, default=None
    )
    model_parameters: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=None
    )
    system_prompt: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, default=None
    )
    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    type: Mapped[AgentType] = mapped_column(
        agent_type_enum, nullable=False, default=AgentType.PUBLIC
    )
    role: Mapped[AgentRole] = mapped_column(
        agent_role_enum, nullable=False, default=AgentRole.AGENT
    )

    runtime_provider_id: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    # Toolkit inherit mode — agent row level ('none' | 'all'), DP1 A, DP2 B.
    # 'all' makes the runtime use the parent agent's toolkits (DP6 — exclusive).
    # 'none' makes the runtime use the subagent's own agent_toolkits.
    # Meaningful only when role='subagent'. Default is 'all' for new subagents.
    toolkit_inherit_mode: Mapped[str] = mapped_column(
        sa.String(10),
        nullable=False,
        default="all",
    )

    # Enable shell access for subagents; meaningful only when role=SUBAGENT.
    shell_enabled: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True
    )
    # Enable the memory system.
    memory_enabled: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True
    )
    max_turns: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True, default=None
    )
    # Profile image JSONB; repositories parse and serialize the StoredImage format.
    avatar: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=None
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

    # Index and constraint condition.
    IX_WORKSPACE_ID = sa.Index("ix_agents_workspace_id", "workspace_id")
    IX_RUNTIME_PROVIDER_ID = sa.Index(
        "ix_agents_runtime_provider_id", "runtime_provider_id"
    )
    CK_MODEL_NOT_NULL = sa.CheckConstraint(
        "model_selection IS NOT NULL AND lightweight_model_selection IS NOT NULL",
        name="ck_agents_model_not_null",
    )
    CK_INHERIT_MODE = sa.CheckConstraint(
        "toolkit_inherit_mode IN ('none', 'all')",
        name="ck_agents_inherit_mode",
    )
    CK_MAX_TURNS_POSITIVE = sa.CheckConstraint(
        "max_turns IS NULL OR max_turns > 0",
        name="ck_agents_max_turns_positive",
    )

    __table_args__ = (
        IX_WORKSPACE_ID,
        IX_RUNTIME_PROVIDER_ID,
        CK_MODEL_NOT_NULL,
        CK_INHERIT_MODE,
        CK_MAX_TURNS_POSITIVE,
    )
