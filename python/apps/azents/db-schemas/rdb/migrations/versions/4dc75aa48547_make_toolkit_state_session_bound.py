"""make toolkit state session bound

Revision ID: 4dc75aa48547
Revises: 2f4e0199c8d1
Create Date: 2026-06-22 02:53:29.099240

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "4dc75aa48547"
down_revision: str | Sequence[str] | None = "2f4e0199c8d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace scoped Toolkit State identity with session-bound identity."""
    op.add_column(
        "toolkit_states",
        sa.Column("agent_id", sa.String(length=32), nullable=True),
    )
    op.execute(
        "DELETE FROM toolkit_states WHERE scope != 'session' OR session_id IS NULL"
    )
    op.execute(
        """
        UPDATE toolkit_states AS ts
        SET agent_id = ar.agent_id
        FROM agent_sessions AS s
        JOIN agent_runtimes AS ar ON ar.id = s.agent_runtime_id
        WHERE ts.session_id = s.id
        """
    )
    op.execute("DELETE FROM toolkit_states WHERE agent_id IS NULL")
    op.alter_column("toolkit_states", "agent_id", nullable=False)

    op.drop_constraint(
        "uq_toolkit_states_identity",
        "toolkit_states",
        type_="unique",
    )
    op.drop_constraint(
        "ck_toolkit_states_scope_session_id",
        "toolkit_states",
        type_="check",
    )
    op.drop_constraint(
        "toolkit_states_agent_runtime_id_fkey",
        "toolkit_states",
        type_="foreignkey",
    )
    op.drop_index("ix_toolkit_states_agent_runtime_id", table_name="toolkit_states")

    op.drop_column("toolkit_states", "scope")
    op.drop_column("toolkit_states", "agent_runtime_id")
    postgresql.ENUM(name="toolkit_state_scope").drop(op.get_bind())

    op.create_foreign_key(
        "toolkit_states_agent_id_fkey",
        "toolkit_states",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_toolkit_states_identity",
        "toolkit_states",
        ["agent_id", "session_id", "toolkit_namespace", "state_name"],
    )
    op.create_index(
        "ix_toolkit_states_agent_id",
        "toolkit_states",
        ["agent_id"],
        unique=False,
    )


def downgrade() -> None:
    """Restore legacy scoped Toolkit State identity."""
    postgresql.ENUM("session", "agent_runtime", name="toolkit_state_scope").create(
        op.get_bind()
    )
    op.add_column(
        "toolkit_states",
        sa.Column(
            "scope",
            postgresql.ENUM(
                "session",
                "agent_runtime",
                name="toolkit_state_scope",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "toolkit_states",
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=True),
    )
    op.execute("UPDATE toolkit_states SET scope = 'session'")
    op.execute(
        """
        UPDATE toolkit_states AS ts
        SET agent_runtime_id = ar.id
        FROM agent_runtimes AS ar
        WHERE ts.agent_id = ar.agent_id
        """
    )
    op.execute("DELETE FROM toolkit_states WHERE agent_runtime_id IS NULL")
    op.alter_column("toolkit_states", "scope", nullable=False)
    op.alter_column("toolkit_states", "agent_runtime_id", nullable=False)

    op.drop_index("ix_toolkit_states_agent_id", table_name="toolkit_states")
    op.drop_constraint(
        "uq_toolkit_states_identity",
        "toolkit_states",
        type_="unique",
    )
    op.drop_constraint(
        "toolkit_states_agent_id_fkey",
        "toolkit_states",
        type_="foreignkey",
    )
    op.drop_column("toolkit_states", "agent_id")

    op.create_foreign_key(
        "toolkit_states_agent_runtime_id_fkey",
        "toolkit_states",
        "agent_runtimes",
        ["agent_runtime_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_toolkit_states_scope_session_id",
        "toolkit_states",
        "(scope = 'session' AND session_id IS NOT NULL) OR "
        "(scope = 'agent_runtime' AND session_id IS NULL)",
    )
    op.create_unique_constraint(
        "uq_toolkit_states_identity",
        "toolkit_states",
        [
            "scope",
            "agent_runtime_id",
            "session_id",
            "toolkit_namespace",
            "state_name",
        ],
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "ix_toolkit_states_agent_runtime_id",
        "toolkit_states",
        ["agent_runtime_id"],
        unique=False,
    )
