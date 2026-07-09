"""Workspace model settings model."""

import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBWorkspaceModelSettings(RDBModel):
    """Workspace default model settings table."""

    __tablename__ = "workspace_model_settings"

    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    default_model_selection: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    default_lightweight_model_selection: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    default_selectable_model_options: Mapped[list[dict[str, Any]] | None] = (
        mapped_column(
            JSONB,
            nullable=True,
            default=None,
        )
    )
    default_main_model_label: Mapped[str | None] = mapped_column(
        sa.String(80), nullable=True, default=None
    )
    default_lightweight_model_label: Mapped[str | None] = mapped_column(
        sa.String(80), nullable=True, default=None
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

    CK_DEFAULT_SELECTABLE_MODEL_OPTIONS_SHAPE = sa.CheckConstraint(
        "default_selectable_model_options IS NULL OR "
        "(jsonb_typeof(default_selectable_model_options) = 'array' "
        "AND jsonb_array_length(default_selectable_model_options) BETWEEN 1 AND 10)",
        name="ck_workspace_model_settings_default_selectable_model_options_shape",
    )

    __table_args__ = (CK_DEFAULT_SELECTABLE_MODEL_OPTIONS_SHAPE,)
