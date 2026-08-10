"""Guard optional Runtime binding downgrade.

Revision ID: 8b9f418cf037
Revises: 4c64a691eddc
Create Date: 2026-08-10 13:48:00.306266

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8b9f418cf037"
down_revision: str | Sequence[str] | None = "4c64a691eddc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Reject rollback after optional Runtime or binding state is activated."""
    unsupported_state_count = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*)
                     FROM agents
                     WHERE runtime_capability != 'managed')
                  + (SELECT count(*)
                     FROM session_agent_contexts
                     WHERE working_folder_binding_state != 'bound'
                        OR working_folder_path IS NULL)
                  + (SELECT count(*)
                     FROM agent_runtime_removal_operations)
                """
            )
        )
        .scalar_one()
    )
    if unsupported_state_count:
        raise RuntimeError(
            "8b9f418cf037 is irreversible after optional Runtime or Session "
            "binding state has been created; recovery requires roll-forward"
        )
