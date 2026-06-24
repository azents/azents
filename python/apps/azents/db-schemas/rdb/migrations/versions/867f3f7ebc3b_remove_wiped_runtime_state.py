"""remove wiped runtime state

Revision ID: 867f3f7ebc3b
Revises: c7f99dfd374e
Create Date: 2026-05-06 08:48:46.337258

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "867f3f7ebc3b"
down_revision: str | Sequence[str] | None = "c7f99dfd374e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove the wiped value from SessionRuntimeState."""
    op.drop_index(
        "ix_agent_runtimes_runtime_state_deadline",
        table_name="agent_runtimes",
    )
    op.execute(
        "UPDATE agent_runtimes "
        "SET runtime_state = 'expired' "
        "WHERE runtime_state = 'wiped'"
    )
    op.execute("ALTER TYPE session_runtime_state RENAME TO session_runtime_state_old")
    op.execute(
        "CREATE TYPE session_runtime_state AS ENUM ('active', 'hibernated', 'expired')"
    )
    op.execute(
        "ALTER TABLE agent_runtimes "
        "ALTER COLUMN runtime_state TYPE session_runtime_state "
        "USING runtime_state::text::session_runtime_state"
    )
    op.execute("DROP TYPE session_runtime_state_old")
    op.create_index(
        "ix_agent_runtimes_runtime_state_deadline",
        "agent_runtimes",
        ["runtime_state", "snapshot_deadline_at"],
        postgresql_where=sa.text("runtime_state = 'active'"),
    )


def downgrade() -> None:
    """Restore the wiped value to SessionRuntimeState."""
    op.drop_index(
        "ix_agent_runtimes_runtime_state_deadline",
        table_name="agent_runtimes",
    )
    op.execute("ALTER TYPE session_runtime_state RENAME TO session_runtime_state_old")
    op.execute(
        "CREATE TYPE session_runtime_state AS ENUM "
        "('active', 'hibernated', 'expired', 'wiped')"
    )
    op.execute(
        "ALTER TABLE agent_runtimes "
        "ALTER COLUMN runtime_state TYPE session_runtime_state "
        "USING runtime_state::text::session_runtime_state"
    )
    op.execute("DROP TYPE session_runtime_state_old")
    op.create_index(
        "ix_agent_runtimes_runtime_state_deadline",
        "agent_runtimes",
        ["runtime_state", "snapshot_deadline_at"],
        postgresql_where=sa.text("runtime_state = 'active'"),
    )
