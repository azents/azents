"""finalize session lifecycle roots

Revision ID: 9f6f27ecb54b
Revises: 23591a43ab9a
Create Date: 2026-07-21 17:17:26.929396

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f6f27ecb54b"
down_revision: str | Sequence[str] | None = "23591a43ab9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    _replace_foreign_key(
        table_name="session_agents",
        constraint_name="session_agents_context_id_fkey",
        columns=["context_id"],
        referent_table="session_agent_contexts",
        referent_columns=["id"],
    )
    _replace_foreign_key(
        table_name="session_agents",
        constraint_name="session_agents_agent_session_id_fkey",
        columns=["agent_session_id"],
        referent_table="agent_sessions",
        referent_columns=["id"],
    )
    _replace_foreign_key(
        table_name="session_agents",
        constraint_name="session_agents_parent_session_agent_id_fkey",
        columns=["parent_session_agent_id"],
        referent_table="session_agents",
        referent_columns=["id"],
    )
    _replace_foreign_key(
        table_name="session_agent_contexts",
        constraint_name="fk_session_agent_contexts_root_session_agent_id_session_agents",
        columns=["root_session_agent_id"],
        referent_table="session_agents",
        referent_columns=["id"],
    )
    _replace_foreign_key(
        table_name="session_agent_context_projects",
        constraint_name="session_agent_context_projects_session_agent_context_id_fkey",
        columns=["session_agent_context_id"],
        referent_table="session_agent_contexts",
        referent_columns=["id"],
    )
    _replace_foreign_key(
        table_name="session_agent_context_git_worktrees",
        constraint_name=(
            "session_agent_context_git_worktrees_session_agent_context_id_fkey"
        ),
        columns=["session_agent_context_id"],
        referent_table="session_agent_contexts",
        referent_columns=["id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    _replace_foreign_key(
        table_name="session_agent_context_git_worktrees",
        constraint_name=(
            "session_agent_context_git_worktrees_session_agent_context_id_fkey"
        ),
        columns=["session_agent_context_id"],
        referent_table="session_agent_contexts",
        referent_columns=["id"],
        ondelete="CASCADE",
    )
    _replace_foreign_key(
        table_name="session_agent_context_projects",
        constraint_name="session_agent_context_projects_session_agent_context_id_fkey",
        columns=["session_agent_context_id"],
        referent_table="session_agent_contexts",
        referent_columns=["id"],
        ondelete="CASCADE",
    )
    _replace_foreign_key(
        table_name="session_agent_contexts",
        constraint_name="fk_session_agent_contexts_root_session_agent_id_session_agents",
        columns=["root_session_agent_id"],
        referent_table="session_agents",
        referent_columns=["id"],
        ondelete="CASCADE",
    )
    _replace_foreign_key(
        table_name="session_agents",
        constraint_name="session_agents_parent_session_agent_id_fkey",
        columns=["parent_session_agent_id"],
        referent_table="session_agents",
        referent_columns=["id"],
        ondelete="CASCADE",
    )
    _replace_foreign_key(
        table_name="session_agents",
        constraint_name="session_agents_agent_session_id_fkey",
        columns=["agent_session_id"],
        referent_table="agent_sessions",
        referent_columns=["id"],
        ondelete="CASCADE",
    )
    _replace_foreign_key(
        table_name="session_agents",
        constraint_name="session_agents_context_id_fkey",
        columns=["context_id"],
        referent_table="session_agent_contexts",
        referent_columns=["id"],
        ondelete="CASCADE",
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
    """Replace one named foreign key with the requested delete action."""
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
