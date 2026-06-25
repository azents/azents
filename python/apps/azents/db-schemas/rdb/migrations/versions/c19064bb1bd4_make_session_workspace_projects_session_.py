"""make session workspace projects session owned

Revision ID: c19064bb1bd4
Revises: 97e8d03b0e20
Create Date: 2026-06-25 16:35:59.110701

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c19064bb1bd4"
down_revision: str | Sequence[str] | None = "97e8d03b0e20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_fk_by_column(table_name: str, column_name: str) -> None:
    """Drop FK constraint for a constrained column."""
    inspector = sa.inspect(op.get_bind())
    for foreign_key in inspector.get_foreign_keys(table_name):
        if foreign_key["constrained_columns"] == [column_name]:
            name = foreign_key["name"]
            if name is None:
                break
            op.drop_constraint(name, table_name, type_="foreignkey")
            return
    raise RuntimeError(f"Foreign key for {table_name}.{column_name} not found")


def upgrade() -> None:
    """Move Project registry ownership from AgentRuntime to AgentSession."""
    op.add_column(
        "session_workspace_projects",
        sa.Column("session_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "session_workspace_project_registration_requests",
        sa.Column("session_id", sa.String(length=32), nullable=True),
    )

    op.execute(
        """
        UPDATE session_workspace_projects AS p
        SET session_id = s.id
        FROM agent_runtimes AS ar
        JOIN agent_sessions AS s
          ON s.agent_id = ar.agent_id
         AND s.status = 'active'
         AND s.primary_kind = 'team_primary'
        WHERE p.agent_runtime_id = ar.id
        """
    )
    op.execute(
        """
        UPDATE session_workspace_project_registration_requests AS r
        SET session_id = s.id
        FROM agent_runtimes AS ar
        JOIN agent_sessions AS s
          ON s.agent_id = ar.agent_id
         AND s.status = 'active'
         AND s.primary_kind = 'team_primary'
        WHERE r.agent_runtime_id = ar.id
        """
    )
    op.execute("DELETE FROM session_workspace_projects WHERE session_id IS NULL")
    op.execute(
        """
        DELETE FROM session_workspace_project_registration_requests
        WHERE session_id IS NULL
        """
    )

    op.drop_constraint(
        "uq_session_workspace_projects_runtime_path",
        "session_workspace_projects",
        type_="unique",
    )
    op.drop_index(
        "ix_session_workspace_projects_agent_runtime_id",
        table_name="session_workspace_projects",
    )
    _drop_fk_by_column("session_workspace_projects", "agent_runtime_id")

    op.drop_index(
        "ix_swp_registration_requests_runtime_status",
        table_name="session_workspace_project_registration_requests",
    )
    op.drop_index(
        "ix_swp_registration_requests_pending_path",
        table_name="session_workspace_project_registration_requests",
    )
    _drop_fk_by_column(
        "session_workspace_project_registration_requests",
        "agent_runtime_id",
    )

    op.alter_column("session_workspace_projects", "session_id", nullable=False)
    op.alter_column(
        "session_workspace_project_registration_requests",
        "session_id",
        nullable=False,
    )

    op.create_foreign_key(
        "session_workspace_projects_session_id_fkey",
        "session_workspace_projects",
        "agent_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "session_workspace_project_registration_requests_session_id_fkey",
        "session_workspace_project_registration_requests",
        "agent_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_session_workspace_projects_session_path",
        "session_workspace_projects",
        ["session_id", "path"],
    )
    op.create_index(
        "ix_session_workspace_projects_session_id",
        "session_workspace_projects",
        ["session_id"],
    )
    op.create_index(
        "ix_swp_registration_requests_session_status",
        "session_workspace_project_registration_requests",
        ["session_id", "status"],
    )
    op.create_index(
        "ix_swp_registration_requests_pending_session_path",
        "session_workspace_project_registration_requests",
        ["session_id", "path"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.drop_column(
        "session_workspace_project_registration_requests",
        "agent_runtime_id",
    )
    op.drop_column("session_workspace_projects", "agent_runtime_id")


def downgrade() -> None:
    """Restore legacy runtime-owned Project registry ownership."""
    op.add_column(
        "session_workspace_projects",
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "session_workspace_project_registration_requests",
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=True),
    )

    op.execute(
        """
        UPDATE session_workspace_projects AS p
        SET agent_runtime_id = ar.id
        FROM agent_sessions AS s
        JOIN agent_runtimes AS ar ON ar.agent_id = s.agent_id
        WHERE p.session_id = s.id
        """
    )
    op.execute(
        """
        UPDATE session_workspace_project_registration_requests AS r
        SET agent_runtime_id = ar.id
        FROM agent_sessions AS s
        JOIN agent_runtimes AS ar ON ar.agent_id = s.agent_id
        WHERE r.session_id = s.id
        """
    )
    op.execute("DELETE FROM session_workspace_projects WHERE agent_runtime_id IS NULL")
    op.execute(
        """
        DELETE FROM session_workspace_project_registration_requests
        WHERE agent_runtime_id IS NULL
        """
    )
    op.execute(
        """
        DELETE FROM session_workspace_projects AS p
        WHERE p.id NOT IN (
            SELECT DISTINCT ON (agent_runtime_id, path) id
            FROM session_workspace_projects
            ORDER BY agent_runtime_id, path, created_at, id
        )
        """
    )
    op.execute(
        """
        DELETE FROM session_workspace_project_registration_requests AS r
        WHERE r.status = 'pending'
          AND r.id NOT IN (
              SELECT DISTINCT ON (agent_runtime_id, path) id
              FROM session_workspace_project_registration_requests
              WHERE status = 'pending'
              ORDER BY agent_runtime_id, path, created_at, id
          )
        """
    )

    op.drop_index(
        "ix_swp_registration_requests_pending_session_path",
        table_name="session_workspace_project_registration_requests",
    )
    op.drop_index(
        "ix_swp_registration_requests_session_status",
        table_name="session_workspace_project_registration_requests",
    )
    op.drop_index(
        "ix_session_workspace_projects_session_id",
        table_name="session_workspace_projects",
    )
    op.drop_constraint(
        "uq_session_workspace_projects_session_path",
        "session_workspace_projects",
        type_="unique",
    )
    op.drop_constraint(
        "session_workspace_project_registration_requests_session_id_fkey",
        "session_workspace_project_registration_requests",
        type_="foreignkey",
    )
    op.drop_constraint(
        "session_workspace_projects_session_id_fkey",
        "session_workspace_projects",
        type_="foreignkey",
    )

    op.alter_column("session_workspace_projects", "agent_runtime_id", nullable=False)
    op.alter_column(
        "session_workspace_project_registration_requests",
        "agent_runtime_id",
        nullable=False,
    )
    op.create_foreign_key(
        "session_workspace_projects_agent_runtime_id_fkey",
        "session_workspace_projects",
        "agent_runtimes",
        ["agent_runtime_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "swp_registration_requests_agent_runtime_id_fkey",
        "session_workspace_project_registration_requests",
        "agent_runtimes",
        ["agent_runtime_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_session_workspace_projects_runtime_path",
        "session_workspace_projects",
        ["agent_runtime_id", "path"],
    )
    op.create_index(
        "ix_session_workspace_projects_agent_runtime_id",
        "session_workspace_projects",
        ["agent_runtime_id"],
    )
    op.create_index(
        "ix_swp_registration_requests_runtime_status",
        "session_workspace_project_registration_requests",
        ["agent_runtime_id", "status"],
    )
    op.create_index(
        "ix_swp_registration_requests_pending_path",
        "session_workspace_project_registration_requests",
        ["agent_runtime_id", "path"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.drop_column("session_workspace_project_registration_requests", "session_id")
    op.drop_column("session_workspace_projects", "session_id")
