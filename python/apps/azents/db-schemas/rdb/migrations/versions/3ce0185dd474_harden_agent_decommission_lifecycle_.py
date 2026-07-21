"""harden agent decommission lifecycle roots

Revision ID: 3ce0185dd474
Revises: 9d73ed4d3a13
Create Date: 2026-07-21 18:28:26.002814

"""

from typing import NamedTuple, Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3ce0185dd474"
down_revision: str | Sequence[str] | None = "9d73ed4d3a13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agent_decommission_jobs",
        sa.Column(
            "requested_by_workspace_user_id",
            sa.String(length=32),
            nullable=True,
        ),
    )
    for specification in _RESTRICTED_FOREIGN_KEYS:
        _replace_foreign_key(
            table_name=specification.table_name,
            constraint_name=specification.constraint_name,
            columns=specification.columns,
            referent_table=specification.referent_table,
            referent_columns=specification.referent_columns,
        )


def downgrade() -> None:
    """Downgrade schema."""
    for specification in reversed(_RESTRICTED_FOREIGN_KEYS):
        _replace_foreign_key(
            table_name=specification.table_name,
            constraint_name=specification.constraint_name,
            columns=specification.columns,
            referent_table=specification.referent_table,
            referent_columns=specification.referent_columns,
            ondelete="CASCADE",
        )
    op.drop_column("agent_decommission_jobs", "requested_by_workspace_user_id")


class _ForeignKeySpecification(NamedTuple):
    """Named source and target metadata for one lifecycle-root foreign key."""

    table_name: str
    constraint_name: str
    columns: list[str]
    referent_table: str
    referent_columns: list[str]


_RESTRICTED_FOREIGN_KEYS: tuple[_ForeignKeySpecification, ...] = (
    _ForeignKeySpecification(
        "agents", "agents_workspace_id_fkey", ["workspace_id"], "workspaces", ["id"]
    ),
    _ForeignKeySpecification(
        "agent_sessions",
        "agent_sessions_workspace_id_fkey",
        ["workspace_id"],
        "workspaces",
        ["id"],
    ),
    _ForeignKeySpecification(
        "agent_sessions",
        "agent_sessions_agent_id_fkey",
        ["agent_id"],
        "agents",
        ["id"],
    ),
    _ForeignKeySpecification(
        "agent_runtimes",
        "agent_runtimes_workspace_id_fkey",
        ["workspace_id"],
        "workspaces",
        ["id"],
    ),
    _ForeignKeySpecification(
        "agent_runtimes",
        "agent_runtimes_agent_id_fkey",
        ["agent_id"],
        "agents",
        ["id"],
    ),
    _ForeignKeySpecification(
        "artifacts", "artifacts_agent_id_fkey", ["agent_id"], "agents", ["id"]
    ),
    _ForeignKeySpecification(
        "exchange_files",
        "exchange_files_agent_id_fkey",
        ["agent_id"],
        "agents",
        ["id"],
    ),
    _ForeignKeySpecification(
        "model_files", "model_files_agent_id_fkey", ["agent_id"], "agents", ["id"]
    ),
    _ForeignKeySpecification(
        "session_agent_contexts",
        "session_agent_contexts_agent_id_fkey",
        ["agent_id"],
        "agents",
        ["id"],
    ),
    _ForeignKeySpecification(
        "toolkit_states",
        "toolkit_states_agent_id_fkey",
        ["agent_id"],
        "agents",
        ["id"],
    ),
)


def _replace_foreign_key(
    *,
    table_name: str,
    constraint_name: str,
    columns: list[str],
    referent_table: str,
    referent_columns: list[str],
    ondelete: str = "RESTRICT",
) -> None:
    """Replace one current foreign key with the requested delete action."""
    column_name = columns[0]
    op.execute(
        f"""
        DO $$
        DECLARE existing_constraint_name text;
        BEGIN
            SELECT usage.constraint_name
            INTO existing_constraint_name
            FROM information_schema.key_column_usage AS usage
            JOIN information_schema.table_constraints AS table_constraint
              ON table_constraint.constraint_catalog = usage.constraint_catalog
             AND table_constraint.constraint_schema = usage.constraint_schema
             AND table_constraint.constraint_name = usage.constraint_name
            WHERE table_constraint.constraint_type = 'FOREIGN KEY'
              AND usage.table_schema = current_schema()
              AND usage.table_name = '{table_name}'
              AND usage.column_name = '{column_name}'
            LIMIT 1;
            IF existing_constraint_name IS NULL THEN
                RAISE EXCEPTION
                    'Expected foreign key missing: %.%',
                    '{table_name}',
                    '{column_name}';
            END IF;
            EXECUTE format(
                'ALTER TABLE {table_name} DROP CONSTRAINT %I',
                existing_constraint_name
            );
        END $$;
        """
    )
    op.create_foreign_key(
        constraint_name,
        table_name,
        referent_table,
        columns,
        referent_columns,
        ondelete=ondelete,
    )
