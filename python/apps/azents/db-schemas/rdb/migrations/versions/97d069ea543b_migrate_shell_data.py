"""Migrate shell data to ShellEnvironment.

Revision ID: 97d069ea543b
Revises: d33eefedef78
Create Date: 2026-03-15

"""

import uuid
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "97d069ea543b"
down_revision: str | Sequence[str] | None = "d33eefedef78"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create default ShellEnvironment and clean up Shell toolkit."""
    conn = op.get_bind()

    # 1. Create a default ShellEnvironment for every existing workspace
    # Skip workspaces that already have one
    workspaces = conn.execute(
        sa.text(
            "SELECT id FROM workspaces WHERE id NOT IN "
            "(SELECT workspace_id FROM shell_environments WHERE is_default = true)"
        )
    ).fetchall()

    for (ws_id,) in workspaces:
        env_id = uuid.uuid4().hex[:32]
        scope_id = uuid.uuid4().hex[:32]
        conn.execute(
            sa.text(
                "INSERT INTO shell_environments "
                "(id, workspace_id, name, is_default, "
                "allowed_domains, denied_domains, "
                "created_at, updated_at) "
                "VALUES (:id, :ws_id, 'Default', "
                "true, '{}', '{}', now(), now())"
            ),
            {"id": env_id, "ws_id": ws_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO shell_environment_scopes "
                "(id, shell_environment_id, scope_type, scope_id, created_at) "
                "VALUES (:id, :env_id, 'workspace', :ws_id, now())"
            ),
            {"id": scope_id, "env_id": env_id, "ws_id": ws_id},
        )

    # 2. Assign the default env to every Agent with role=agent
    conn.execute(
        sa.text(
            "UPDATE agents SET shell_environment_id = ("
            "  SELECT se.id FROM shell_environments se "
            "  WHERE se.workspace_id = agents.workspace_id AND se.is_default = true"
            ") WHERE role = 'agent' AND shell_environment_id IS NULL"
        )
    )

    # 3. Delete Shell AgentToolkit
    conn.execute(sa.text("DELETE FROM agent_toolkits WHERE toolkit_type = 'shell'"))

    # 4. Delete Shell ToolkitScope
    conn.execute(
        sa.text(
            "DELETE FROM toolkit_scopes WHERE toolkit_id IN ("
            "  SELECT id FROM toolkit_configs WHERE toolkit_type = 'shell'"
            ")"
        )
    )

    # 5. Delete Shell ToolkitConfig
    conn.execute(sa.text("DELETE FROM toolkit_configs WHERE toolkit_type = 'shell'"))


def downgrade() -> None:
    """Roll back data migration by deleting the generated default env."""
    conn = op.get_bind()
    # Clear shell_environment_id from Agents
    conn.execute(sa.text("UPDATE agents SET shell_environment_id = NULL"))
    # Delete Shell environment scopes
    conn.execute(sa.text("DELETE FROM shell_environment_scopes"))
    # Delete Shell environments
    conn.execute(sa.text("DELETE FROM shell_environments"))
