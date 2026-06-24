"""add agents table

Revision ID: 453c23cfa3f5
Revises: b5d2f4a83c17
Create Date: 2026-02-22 00:15:21.391660

"""

# pyright: reportUnknownArgumentType=false

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "453c23cfa3f5"
down_revision: str | Sequence[str] | None = "b5d2f4a83c17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the agents and agent_admins tables."""
    # Create the agent_type ENUM
    agent_type_enum = postgresql.ENUM(
        "public", "private", name="agent_type", create_type=False
    )
    agent_type_enum.create(op.get_bind(), checkfirst=True)

    # Create the agents table
    op.create_table(
        "agents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "llm_provider_integration_id",
            sa.String(32),
            sa.ForeignKey("llm_provider_integrations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "llm_provider_model_provider",
            postgresql.ENUM(
                "openai",
                "anthropic",
                "google_gemini",
                "aws_bedrock",
                "google_vertex_ai",
                name="llm_provider",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("llm_provider_model_identifier", sa.String(255), nullable=False),
        sa.Column("model_parameters", postgresql.JSONB, nullable=True),
        sa.Column("system_prompt", sa.Text, nullable=True),
        sa.Column(
            "enabled", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "type",
            postgresql.ENUM("public", "private", name="agent_type", create_type=False),
            nullable=False,
            server_default=sa.text("'public'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["llm_provider_model_provider", "llm_provider_model_identifier"],
            ["llm_provider_models.provider", "llm_provider_models.model_identifier"],
            name="fk_agents_llm_provider_model",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_agents_workspace_id", "agents", ["workspace_id"])

    # Create the agent_admins table
    op.create_table(
        "agent_admins",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "agent_id",
            sa.String(32),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_user_id",
            sa.String(32),
            sa.ForeignKey("workspace_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "agent_id",
            "workspace_user_id",
            name="uq_agent_admins_agent_workspace_user",
        ),
    )
    op.create_index("ix_agent_admins_agent_id", "agent_admins", ["agent_id"])
    op.create_index(
        "ix_agent_admins_workspace_user_id",
        "agent_admins",
        ["workspace_user_id"],
    )


def downgrade() -> None:
    """Drop the agent_admins and agents tables."""
    op.drop_index("ix_agent_admins_workspace_user_id", table_name="agent_admins")
    op.drop_index("ix_agent_admins_agent_id", table_name="agent_admins")
    op.drop_table("agent_admins")

    op.drop_index("ix_agents_workspace_id", table_name="agents")
    op.drop_table("agents")

    postgresql.ENUM(name="agent_type").drop(op.get_bind(), checkfirst=True)
