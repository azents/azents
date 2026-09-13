"""Workspace-scoped physical model candidate health authority."""

import datetime
import enum

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import ModelCandidateClaimKind
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in PostgreSQL."""
    return [value.value for value in enum_cls]


model_candidate_claim_kind_enum = ENUM(
    ModelCandidateClaimKind,
    name="model_candidate_claim_kind",
    create_type=False,
    values_callable=_enum_values,
)


class RDBModelCandidateHealth(RDBModel):
    """Durable cooldown and exclusive recovery claim for one candidate."""

    __tablename__ = "model_candidate_health"

    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    llm_provider_integration_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("llm_provider_integrations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    model_identifier: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    cooldown_until: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    claim_kind: Mapped[ModelCandidateClaimKind | None] = mapped_column(
        model_candidate_claim_kind_enum,
        nullable=True,
        default=None,
    )
    claim_owner_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    claim_token: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        default=None,
    )
    claim_until: Mapped[datetime.datetime | None] = mapped_column(
        TimeZoneDateTime,
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

    IX_COOLDOWN_UNTIL = sa.Index(
        "ix_model_candidate_health_cooldown_until",
        "cooldown_until",
    )
    CK_GENERATION_POSITIVE = sa.CheckConstraint(
        "generation >= 1",
        name="ck_model_candidate_health_generation_positive",
    )
    CK_CLAIM_COMPLETE = sa.CheckConstraint(
        "(claim_kind IS NULL AND claim_owner_id IS NULL "
        "AND claim_token IS NULL AND claim_until IS NULL) OR "
        "(claim_kind IS NOT NULL AND claim_owner_id IS NOT NULL "
        "AND claim_token IS NOT NULL AND claim_until IS NOT NULL)",
        name="ck_model_candidate_health_claim_complete",
    )

    __table_args__ = (
        IX_COOLDOWN_UNTIL,
        CK_GENERATION_POSITIVE,
        CK_CLAIM_COMPLETE,
    )
