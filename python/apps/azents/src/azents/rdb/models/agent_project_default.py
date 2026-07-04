"""Agent Project default model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import AgentProjectDefaultItemType
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _agent_project_default_item_type_values(
    enum_cls: type[AgentProjectDefaultItemType],
) -> list[str]:
    """Return AgentProjectDefaultItemType enum values stored in the DB."""
    return [v.value for v in enum_cls]


agent_project_default_item_type_enum = ENUM(
    AgentProjectDefaultItemType,
    name="agent_project_default_item_type",
    create_type=False,
    values_callable=_agent_project_default_item_type_values,
)


class RDBAgentProjectDefault(RDBModel):
    """Agent-owned default workspace item for new sessions."""

    __tablename__ = "agent_project_defaults"

    UQ_AGENT_POSITION = sa.UniqueConstraint(
        "agent_id",
        "position",
        name="uq_agent_project_defaults_agent_position",
    )
    IX_AGENT_POSITION = sa.Index(
        "ix_agent_project_defaults_agent_position",
        "agent_id",
        "position",
    )

    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(sa.Text, nullable=False)
    position: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    item_type: Mapped[AgentProjectDefaultItemType] = mapped_column(
        agent_project_default_item_type_enum,
        nullable=False,
        default=AgentProjectDefaultItemType.EXISTING_PROJECT,
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
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

    __table_args__ = (UQ_AGENT_POSITION, IX_AGENT_POSITION)
