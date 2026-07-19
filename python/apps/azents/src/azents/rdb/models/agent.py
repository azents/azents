"""Agent model."""

import datetime
from typing import Any

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.agent import (
    DEFAULT_SUBAGENT_MAX_DEPTH,
    DEFAULT_SUBAGENT_MAX_SUBAGENTS,
)
from azents.core.enums import AgentType
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


class RDBAgent(RDBModel):
    """Agent table.

    Workspace-scoped settings for LLM model, parameters, and system prompt.
    """

    __tablename__ = "agents"

    def __post_init__(self) -> None:
        """Populate selectable model options for legacy test constructors."""
        if self.selectable_model_options is None:
            options = [
                {
                    "label": "default",
                    "model_selection": self.model_selection,
                    "settings": {
                        "context_window_tokens": None,
                        "max_output_tokens": None,
                        "builtin_tools": [],
                        "subagent_enabled": True,
                        "subagent_guidance": None,
                    },
                }
            ]
            if self.model_selection != self.lightweight_model_selection:
                options.append(
                    {
                        "label": "lightweight",
                        "model_selection": self.lightweight_model_selection,
                        "settings": {
                            "context_window_tokens": None,
                            "max_output_tokens": None,
                            "builtin_tools": [],
                            "subagent_enabled": True,
                            "subagent_guidance": None,
                        },
                    }
                )
            self.selectable_model_options = options
        if self.main_model_label is None:
            self.main_model_label = "default"
        if self.lightweight_model_label is None:
            self.lightweight_model_label = (
                "default"
                if self.model_selection == self.lightweight_model_selection
                else "lightweight"
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
    name: Mapped[str] = mapped_column(sa.String(100), nullable=False)

    model_selection: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    lightweight_model_selection: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    selectable_model_options: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB,
        nullable=False,
        default=None,
    )
    main_model_label: Mapped[str | None] = mapped_column(
        sa.String(80), nullable=False, default=None
    )
    lightweight_model_label: Mapped[str | None] = mapped_column(
        sa.String(80), nullable=False, default=None
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
    runtime_provider_id: Mapped[str | None] = mapped_column(
        sa.String(120),
        nullable=True,
        default=None,
    )
    # Enable runtime shell access.
    shell_enabled: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True
    )
    # Enable the memory system.
    memory_enabled: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True
    )
    # Enable deferred Tool Search and bounded model-visible tool projection.
    tool_search_enabled: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=False,
        server_default=sa.false(),
    )
    max_turns: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True, default=None
    )
    subagent_settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default_factory=lambda: {
            "max_subagents": DEFAULT_SUBAGENT_MAX_SUBAGENTS,
            "max_depth": DEFAULT_SUBAGENT_MAX_DEPTH,
        },
        server_default=sa.text(
            f'\'{{"max_subagents": {DEFAULT_SUBAGENT_MAX_SUBAGENTS}, '
            f'"max_depth": {DEFAULT_SUBAGENT_MAX_DEPTH}}}\'::jsonb'
        ),
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
    CK_MAX_TURNS_POSITIVE = sa.CheckConstraint(
        "max_turns IS NULL OR max_turns > 0",
        name="ck_agents_max_turns_positive",
    )
    CK_SELECTABLE_MODEL_OPTIONS_SHAPE = sa.CheckConstraint(
        "jsonb_typeof(selectable_model_options) = 'array' "
        "AND jsonb_array_length(selectable_model_options) BETWEEN 1 AND 10",
        name="ck_agents_selectable_model_options_shape",
    )
    CK_SUBAGENT_SETTINGS_SHAPE = sa.CheckConstraint(
        "jsonb_typeof(subagent_settings) = 'object' "
        "AND (subagent_settings ? 'max_subagents') "
        "AND (subagent_settings ? 'max_depth') "
        "AND jsonb_typeof(subagent_settings->'max_subagents') = 'number' "
        "AND jsonb_typeof(subagent_settings->'max_depth') = 'number' "
        "AND (subagent_settings->>'max_subagents')::integer >= 0 "
        "AND (subagent_settings->>'max_depth')::integer >= 0",
        name="ck_agents_subagent_settings_shape",
    )

    __table_args__ = (
        IX_WORKSPACE_ID,
        IX_RUNTIME_PROVIDER_ID,
        CK_MODEL_NOT_NULL,
        CK_MAX_TURNS_POSITIVE,
        CK_SELECTABLE_MODEL_OPTIONS_SHAPE,
        CK_SUBAGENT_SETTINGS_SHAPE,
    )
