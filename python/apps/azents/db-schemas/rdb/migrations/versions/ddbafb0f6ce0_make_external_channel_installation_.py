"""make external channel installation identity global

Revision ID: ddbafb0f6ce0
Revises: 498257a85dc8
Create Date: 2026-07-22 17:42:21.721457

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ddbafb0f6ce0"
down_revision: str | Sequence[str] | None = "498257a85dc8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        sa.text(
            """
            UPDATE external_channel_connections
            SET provider_tenant_id = NULL,
                provider_bot_user_id = NULL,
                capabilities = NULL
            WHERE status = 'disconnected'
            """
        )
    )
    duplicate_groups = op.get_bind().scalar(
        sa.text(
            """
            SELECT count(*)
            FROM (
                SELECT provider, provider_tenant_id, provider_app_id
                FROM external_channel_connections
                WHERE provider_tenant_id IS NOT NULL
                  AND provider_app_id IS NOT NULL
                GROUP BY provider, provider_tenant_id, provider_app_id
                HAVING count(*) > 1
            ) AS duplicate_installations
            """
        )
    )
    if duplicate_groups:
        raise RuntimeError(
            "Cannot make External Channel installation identity global: "
            f"{duplicate_groups} duplicate installation group(s) remain. "
            "Disconnect duplicate installations before retrying the migration."
        )
    op.drop_index(
        "uq_external_channel_connections_installation_identity",
        table_name="external_channel_connections",
    )
    op.create_index(
        "uq_external_channel_connections_installation_identity",
        "external_channel_connections",
        ["provider", "provider_tenant_id", "provider_app_id"],
        unique=True,
        postgresql_where=sa.text(
            "provider_tenant_id IS NOT NULL AND provider_app_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uq_external_channel_connections_installation_identity",
        table_name="external_channel_connections",
    )
    op.create_index(
        "uq_external_channel_connections_installation_identity",
        "external_channel_connections",
        ["workspace_id", "provider", "provider_tenant_id", "provider_app_id"],
        unique=True,
        postgresql_where=sa.text(
            "provider_tenant_id IS NOT NULL AND provider_app_id IS NOT NULL"
        ),
    )
