"""add chatgpt oauth provider schema

Revision ID: 8974ac24b005
Revises: 6308254dd81b
Create Date: 2026-05-02 15:50:55.033857

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8974ac24b005"
down_revision: str | Sequence[str] | None = "6308254dd81b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the ChatGPT OAuth provider schema."""
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE llm_provider ADD VALUE IF NOT EXISTS 'chatgpt_oauth'")
    sa.Enum(
        "callback",
        "device",
        name="chatgpt_oauth_connection_method",
    ).create(op.get_bind())
    sa.Enum(
        "pending",
        "connected",
        "cancelled",
        "expired",
        "failed",
        name="chatgpt_oauth_session_status",
    ).create(op.get_bind())

    connection_method_enum = postgresql.ENUM(
        name="chatgpt_oauth_connection_method", create_type=False
    )
    session_status_enum = postgresql.ENUM(
        name="chatgpt_oauth_session_status", create_type=False
    )

    op.create_table(
        "chatgpt_oauth_sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("method", connection_method_enum, nullable=False),
        sa.Column("state", sa.String(128), nullable=False),
        sa.Column("encrypted_code_verifier", sa.Text, nullable=False),
        sa.Column("redirect_uri", sa.Text, nullable=False),
        sa.Column("encrypted_device_auth_id", sa.Text, nullable=True),
        sa.Column("user_code", sa.String(64), nullable=True),
        sa.Column("verification_uri", sa.Text, nullable=True),
        sa.Column("interval_seconds", sa.Integer, nullable=True),
        sa.Column(
            "status",
            session_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_chatgpt_oauth_sessions_workspace_id",
        "chatgpt_oauth_sessions",
        ["workspace_id"],
    )
    op.create_index(
        "ix_chatgpt_oauth_sessions_user_id",
        "chatgpt_oauth_sessions",
        ["user_id"],
    )
    op.create_index(
        "ix_chatgpt_oauth_sessions_state",
        "chatgpt_oauth_sessions",
        ["state"],
        unique=True,
    )

    op.execute(
        """
        INSERT INTO llm_models (slug, vendor, name, description)
        VALUES
            (
                'gpt-5.1-codex',
                'openai',
                'GPT-5.1 Codex',
                'ChatGPT subscription Codex agent model'
            ),
            (
                'gpt-5.1-codex-max',
                'openai',
                'GPT-5.1 Codex Max',
                'ChatGPT subscription Codex high-capability agent model'
            )
        ON CONFLICT (slug) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO llm_provider_models (
            id,
            provider,
            model_identifier,
            model_slug,
            available,
            thinking,
            metadata
        )
        VALUES
            (
                replace(gen_random_uuid()::text, '-', ''),
                'chatgpt_oauth',
                'gpt-5.1-codex',
                'gpt-5.1-codex',
                false,
                true,
                '{"source": "chatgpt_subscription"}'::jsonb
            ),
            (
                replace(gen_random_uuid()::text, '-', ''),
                'chatgpt_oauth',
                'gpt-5.1-codex-max',
                'gpt-5.1-codex-max',
                false,
                true,
                '{"source": "chatgpt_subscription"}'::jsonb
            )
        ON CONFLICT (provider, model_identifier) DO NOTHING
        """
    )


def downgrade() -> None:
    """Remove the ChatGPT OAuth provider schema."""
    op.execute(
        """
        DELETE FROM llm_provider_models
        WHERE provider = 'chatgpt_oauth'
          AND model_identifier IN ('gpt-5.1-codex', 'gpt-5.1-codex-max')
        """
    )
    op.execute(
        """
        DELETE FROM llm_models
        WHERE slug IN ('gpt-5.1-codex', 'gpt-5.1-codex-max')
          AND NOT EXISTS (
              SELECT 1
              FROM llm_provider_models
              WHERE llm_provider_models.model_slug = llm_models.slug
          )
        """
    )
    op.drop_index(
        "ix_chatgpt_oauth_sessions_state", table_name="chatgpt_oauth_sessions"
    )
    op.drop_index(
        "ix_chatgpt_oauth_sessions_user_id", table_name="chatgpt_oauth_sessions"
    )
    op.drop_index(
        "ix_chatgpt_oauth_sessions_workspace_id",
        table_name="chatgpt_oauth_sessions",
    )
    op.drop_table("chatgpt_oauth_sessions")
    sa.Enum(name="chatgpt_oauth_session_status").drop(op.get_bind())
    sa.Enum(name="chatgpt_oauth_connection_method").drop(op.get_bind())
