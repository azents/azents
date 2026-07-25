"""add provider output provenance

Revision ID: b6088a911203
Revises: 1ce295000a20
Create Date: 2026-07-24 19:15:53.881548

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6088a911203"
down_revision: str | Sequence[str] | None = "1ce295000a20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add Userless provider-output provenance and exact Run lineage."""
    op.add_column(
        "model_files",
        sa.Column("created_run_id", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        UPDATE model_files AS model_file
        SET created_run_id = agent_run.id
        FROM agent_runs AS agent_run
        WHERE agent_run.session_id = model_file.session_id
          AND agent_run.run_index = model_file.created_run_index
        """
    )
    op.create_foreign_key(
        "fk_model_files_created_run_id_agent_runs",
        "model_files",
        "agent_runs",
        ["created_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.execute(
        """
        CREATE TYPE exchange_file_provenance_kind AS ENUM (
            'human', 'agent', 'tool', 'provider', 'system', 'preview', 'migration'
        )
        """
    )
    provenance_enum = sa.Enum(
        "human",
        "agent",
        "tool",
        "provider",
        "system",
        "preview",
        "migration",
        name="exchange_file_provenance_kind",
        create_type=False,
    )
    op.alter_column(
        "exchange_files",
        "created_by_user_id",
        existing_type=sa.String(length=32),
        nullable=True,
    )
    op.add_column(
        "exchange_files",
        sa.Column("provenance_kind", provenance_enum, nullable=True),
    )
    for column in (
        sa.Column("source_user_id", sa.String(length=32), nullable=True),
        sa.Column("source_agent_id", sa.String(length=32), nullable=True),
        sa.Column("source_run_id", sa.String(length=32), nullable=True),
        sa.Column("source_tool_name", sa.String(length=255), nullable=True),
        sa.Column("source_provider", sa.String(length=255), nullable=True),
        sa.Column("source_exchange_file_id", sa.String(length=32), nullable=True),
    ):
        op.add_column("exchange_files", column)
    op.execute(
        """
        UPDATE exchange_files
        SET provenance_kind = 'migration',
            source_user_id = created_by_user_id
        """
    )
    op.create_foreign_key(
        "fk_exchange_files_source_user_id_users",
        "exchange_files",
        "users",
        ["source_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_exchange_files_source_agent_id_agents",
        "exchange_files",
        "agents",
        ["source_agent_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_exchange_files_source_run_id_agent_runs",
        "exchange_files",
        "agent_runs",
        ["source_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_exchange_files_source_exchange_file_id_exchange_files",
        "exchange_files",
        "exchange_files",
        ["source_exchange_file_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Remove Userless provider-output provenance and exact Run lineage."""
    unresolved = op.get_bind().scalar(
        sa.text(
            """
            SELECT count(*)
            FROM exchange_files
            WHERE created_by_user_id IS NULL
            """
        )
    )
    if unresolved:
        raise RuntimeError("Cannot restore ExchangeFile Human creator ownership")
    for name in (
        "fk_exchange_files_source_exchange_file_id_exchange_files",
        "fk_exchange_files_source_run_id_agent_runs",
        "fk_exchange_files_source_agent_id_agents",
        "fk_exchange_files_source_user_id_users",
    ):
        op.drop_constraint(name, "exchange_files", type_="foreignkey")
    for column in (
        "source_exchange_file_id",
        "source_provider",
        "source_tool_name",
        "source_run_id",
        "source_agent_id",
        "source_user_id",
        "provenance_kind",
    ):
        op.drop_column("exchange_files", column)
    op.alter_column(
        "exchange_files",
        "created_by_user_id",
        existing_type=sa.String(length=32),
        nullable=False,
    )
    op.execute("DROP TYPE exchange_file_provenance_kind")

    op.drop_constraint(
        "fk_model_files_created_run_id_agent_runs",
        "model_files",
        type_="foreignkey",
    )
    op.drop_column("model_files", "created_run_id")
