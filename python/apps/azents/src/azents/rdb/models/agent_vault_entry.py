"""Agent-owned encrypted Vault records."""

import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBAgentVaultEntry(RDBModel):
    """One named value; the contributor label confers no authority."""

    __tablename__ = "agent_vault_entries"

    agent_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    name: Mapped[str] = mapped_column(sa.String(255, collation="C"), primary_key=True)
    encrypted_value: Mapped[str] = mapped_column(sa.Text, repr=False, nullable=False)
    contributor_label: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime, init=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        init=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )
