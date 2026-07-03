"""Agent Project catalog model."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import AgentProjectCatalogStatus
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _agent_project_catalog_status_values(
    enum_cls: type[AgentProjectCatalogStatus],
) -> list[str]:
    """Return Agent Project catalog status enum values stored in the DB."""
    return [v.value for v in enum_cls]


agent_project_catalog_status_enum = ENUM(
    AgentProjectCatalogStatus,
    name="agent_project_catalog_status",
    create_type=False,
    values_callable=_agent_project_catalog_status_values,
)


class RDBAgentProjectCatalogEntry(RDBModel):
    """Agent-scoped Project path candidate and filesystem status projection."""

    __tablename__ = "agent_project_catalog_entries"

    UQ_AGENT_PATH = sa.UniqueConstraint(
        "agent_id",
        "path",
        name="uq_agent_project_catalog_entries_agent_path",
    )
    IX_AGENT_UPDATED = sa.Index(
        "ix_agent_project_catalog_entries_agent_updated",
        "agent_id",
        "updated_at",
    )

    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[AgentProjectCatalogStatus] = mapped_column(
        agent_project_catalog_status_enum,
        nullable=False,
        default=AgentProjectCatalogStatus.UNCHECKED,
        server_default=AgentProjectCatalogStatus.UNCHECKED.value,
    )
    status_detail: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    checked_at: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
        nullable=True,
        default=None,
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

    __table_args__ = (UQ_AGENT_PATH, IX_AGENT_UPDATED)
