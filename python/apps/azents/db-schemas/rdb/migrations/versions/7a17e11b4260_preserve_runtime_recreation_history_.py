"""Preserve Runtime recreation history after terminal deletion."""

from typing import Sequence

from alembic import op

revision: str = "7a17e11b4260"
down_revision: str | Sequence[str] | None = "e67a51c3c652"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Release terminal Runtime ownership without changing historical items."""
    op.drop_constraint(
        "runtime_recreation_operation_items_runtime_id_fkey",
        "runtime_recreation_operation_items",
        type_="foreignkey",
    )


def downgrade() -> None:
    """Restore ownership only when all historical targets still exist.

    PostgreSQL rejects this downgrade if a Runtime has already been deleted.
    Historical items must not be deleted or rewritten to make rollback succeed.
    """
    op.create_foreign_key(
        "runtime_recreation_operation_items_runtime_id_fkey",
        "runtime_recreation_operation_items",
        "agent_runtimes",
        ["runtime_id"],
        ["id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
