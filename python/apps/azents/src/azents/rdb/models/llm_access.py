"""Agent-owned inference supplies and hash-only bearer tokens."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.orm import Mapped, mapped_column

from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


class RDBLLMAccessSupply(RDBModel):
    """Lifecycle boundary for one trusted consumer of an Agent."""

    __tablename__ = "llm_access_supplies"
    UQ_SUBJECT = sa.UniqueConstraint(
        "agent_id", "subject", name="uq_llm_access_supply_subject"
    )
    IX_AGENT = sa.Index("ix_llm_access_supplies_agent_id", "agent_id")

    id: Mapped[str] = mapped_column(
        sa.String(32), primary_key=True, init=False, default_factory=lambda: uuid7().hex
    )
    agent_id: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("agents.id", ondelete="CASCADE")
    )
    subject: Mapped[str] = mapped_column(sa.String(256))
    issuer: Mapped[str] = mapped_column(sa.String(256))
    current_token_id: Mapped[str | None] = mapped_column(sa.String(32))
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(TimeZoneDateTime)
    created_at: Mapped[datetime.datetime] = mapped_column(TimeZoneDateTime)

    __table_args__ = (UQ_SUBJECT, IX_AGENT)


class RDBLLMAccessToken(RDBModel):
    """A nonrecoverable credential linked to its supply target."""

    __tablename__ = "llm_access_tokens"
    UQ_DIGEST = sa.UniqueConstraint("digest", name="uq_llm_access_tokens_digest")
    IX_SUPPLY = sa.Index("ix_llm_access_tokens_supply_id", "supply_id")

    id: Mapped[str] = mapped_column(
        sa.String(32), primary_key=True, init=False, default_factory=lambda: uuid7().hex
    )
    supply_id: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("llm_access_supplies.id", ondelete="CASCADE")
    )
    digest: Mapped[str] = mapped_column(sa.String(64))
    issued_at: Mapped[datetime.datetime] = mapped_column(TimeZoneDateTime)
    expires_at: Mapped[datetime.datetime] = mapped_column(TimeZoneDateTime)
    handover_until: Mapped[datetime.datetime | None] = mapped_column(TimeZoneDateTime)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(TimeZoneDateTime)

    __table_args__ = (UQ_DIGEST, IX_SUPPLY)
