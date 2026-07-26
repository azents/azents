"""Durable coordination claims for manual Git worktree cleanup."""

import datetime
import enum

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from azents.core.enums import (
    GitWorktreePathClaimOwnerKind,
    GitWorktreePathClaimState,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.types.datetime import TimeZoneDateTime


def _enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """Return StrEnum values stored in the database."""
    return [value.value for value in enum_cls]


git_worktree_path_claim_owner_kind_enum = ENUM(
    GitWorktreePathClaimOwnerKind,
    name="git_worktree_path_claim_owner_kind",
    create_type=False,
    values_callable=_enum_values,
)
git_worktree_path_claim_state_enum = ENUM(
    GitWorktreePathClaimState,
    name="git_worktree_path_claim_state",
    create_type=False,
    values_callable=_enum_values,
)


class RDBGitWorktreePathClaim(RDBModel):
    """Reserve one Runtime worktree path during destructive Git operations."""

    __tablename__ = "git_worktree_path_claims"

    IX_AGENT_RUNTIME_ID = sa.Index(
        "ix_git_worktree_path_claims_agent_runtime_id",
        "agent_runtime_id",
    )
    IX_ACTION_EXECUTION_ID = sa.Index(
        "ix_git_worktree_path_claims_action_execution_id",
        "action_execution_id",
    )
    IX_ROOT_SESSION_ID = sa.Index(
        "ix_git_worktree_path_claims_root_session_id",
        "root_session_id",
    )
    UQ_RUNTIME_PATH = sa.UniqueConstraint(
        "agent_runtime_id",
        "worktree_path",
        name="uq_git_worktree_path_claims_agent_runtime_path",
    )

    id: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        init=False,
        default_factory=lambda: uuid7().hex,
    )
    agent_runtime_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_runtimes.id", ondelete="CASCADE"),
        nullable=False,
    )
    worktree_path: Mapped[str] = mapped_column(sa.Text, nullable=False)
    owner_kind: Mapped[GitWorktreePathClaimOwnerKind] = mapped_column(
        git_worktree_path_claim_owner_kind_enum,
        nullable=False,
    )
    lease_until: Mapped[datetime.datetime] = mapped_column(
        TimeZoneDateTime,
        nullable=False,
    )
    action_execution_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("action_executions.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    root_session_id: Mapped[str | None] = mapped_column(
        sa.String(32),
        sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )
    owner_generation: Mapped[int | None] = mapped_column(
        sa.BigInteger,
        nullable=True,
        default=None,
    )
    discovery_fingerprint: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    state: Mapped[GitWorktreePathClaimState] = mapped_column(
        git_worktree_path_claim_state_enum,
        nullable=False,
        default=GitWorktreePathClaimState.CLAIMED,
    )
    reason_code: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        default=None,
    )
    summary: Mapped[str | None] = mapped_column(
        sa.Text,
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

    __table_args__ = (
        IX_AGENT_RUNTIME_ID,
        IX_ACTION_EXECUTION_ID,
        IX_ROOT_SESSION_ID,
        UQ_RUNTIME_PATH,
    )
