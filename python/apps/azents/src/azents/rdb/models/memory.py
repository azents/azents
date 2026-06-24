"""Agent Memory model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

import azents.rdb.models.agent as _  # noqa: F401  # Register FK target table metadata.
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime

memory_scope_enum = ENUM("agent", "user", name="memory_scope", create_type=False)


class RDBAgentMemory(RDBModel):
    """Agent Memory table.

    Stores Agent memories and distinguishes agent-scoped memories from
    user-scoped memories.
    """

    __tablename__ = "agent_memories"

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
    scope: Mapped[str] = mapped_column(memory_scope_enum, nullable=False)
    type: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)

    # Optional field. Defaults are required only when explicitly needed.
    user_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
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
    __table_args__ = (
        # Partial unique: agent scope — (agent_id, name) WHERE user_id IS NULL
        sa.Index(
            "uq_agent_memories_agent_scope",
            "agent_id",
            "name",
            unique=True,
            postgresql_where=sa.text("user_id IS NULL"),
        ),
        # Partial unique: user scope — (agent_id, user_id, name)
        # WHERE user_id IS NOT NULL
        sa.Index(
            "uq_agent_memories_user_scope",
            "agent_id",
            "user_id",
            "name",
            unique=True,
            postgresql_where=sa.text("user_id IS NOT NULL"),
        ),
        # Regular: agent scope lookup
        sa.Index(
            "ix_agent_memories_agent_id",
            "agent_id",
            postgresql_where=sa.text("user_id IS NULL"),
        ),
        # Regular: user scope lookup
        sa.Index(
            "ix_agent_memories_agent_user",
            "agent_id",
            "user_id",
            postgresql_where=sa.text("user_id IS NOT NULL"),
        ),
    )
