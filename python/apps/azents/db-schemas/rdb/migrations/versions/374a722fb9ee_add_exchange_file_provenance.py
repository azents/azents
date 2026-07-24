"""add exchange file provenance

Revision ID: 374a722fb9ee
Revises: 8fae7b9ab00a
Create Date: 2026-07-24 14:41:44.186749

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "374a722fb9ee"
down_revision: str | Sequence[str] | None = "8fae7b9ab00a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace creator ownership with typed source provenance."""
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
    op.alter_column("exchange_files", "provenance_kind", nullable=False)
    inspector = sa.inspect(op.get_bind())
    for foreign_key in inspector.get_foreign_keys("exchange_files"):
        if foreign_key["constrained_columns"] == ["created_by_user_id"]:
            name = foreign_key["name"]
            if name is not None:
                op.drop_constraint(name, "exchange_files", type_="foreignkey")
            break
    op.drop_column("exchange_files", "created_by_user_id")
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
    op.create_check_constraint(
        "ck_exchange_files_provenance",
        "exchange_files",
        """
        (provenance_kind = 'human' AND source_user_id IS NOT NULL)
        OR (provenance_kind = 'agent' AND source_agent_id IS NOT NULL)
        OR (
            provenance_kind = 'tool'
            AND source_agent_id IS NOT NULL
            AND source_run_id IS NOT NULL
            AND source_tool_name IS NOT NULL
        )
        OR (
            provenance_kind = 'provider'
            AND source_agent_id IS NOT NULL
            AND source_run_id IS NOT NULL
            AND source_provider IS NOT NULL
        )
        OR (provenance_kind IN ('system', 'migration'))
        OR (
            provenance_kind = 'preview'
            AND source_exchange_file_id IS NOT NULL
        )
        """,
    )


def downgrade() -> None:
    """Restore legacy ExchangeFile creator ownership."""
    op.drop_constraint(
        "ck_exchange_files_provenance",
        "exchange_files",
        type_="check",
    )
    for name in (
        "fk_exchange_files_source_exchange_file_id_exchange_files",
        "fk_exchange_files_source_run_id_agent_runs",
        "fk_exchange_files_source_agent_id_agents",
        "fk_exchange_files_source_user_id_users",
    ):
        op.drop_constraint(name, "exchange_files", type_="foreignkey")
    op.add_column(
        "exchange_files",
        sa.Column("created_by_user_id", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        UPDATE exchange_files
        SET created_by_user_id = source_user_id
        WHERE source_user_id IS NOT NULL
        """
    )
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
        raise RuntimeError("Cannot restore ExchangeFile creator User provenance")
    op.alter_column("exchange_files", "created_by_user_id", nullable=False)
    op.create_foreign_key(
        "fk_exchange_files_created_by_user_id_users",
        "exchange_files",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="CASCADE",
    )
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
    op.execute("DROP TYPE exchange_file_provenance_kind")
