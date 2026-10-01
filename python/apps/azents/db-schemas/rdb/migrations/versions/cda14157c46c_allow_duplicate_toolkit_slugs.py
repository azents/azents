from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "cda14157c46c"
down_revision: str | Sequence[str] | None = "a0dac2fe3ca2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index(
        "uq_toolkit_configs_shared_workspace_slug",
        table_name="toolkit_configs",
    )
    op.drop_index(
        "uq_toolkit_configs_owner_agent_slug",
        table_name="toolkit_configs",
    )


def downgrade() -> None:
    """Downgrade schema."""
    connection = op.get_bind()
    duplicate = connection.execute(
        sa.text(
            """
            WITH effective_toolkits AS (
                SELECT agent_toolkits.agent_id, toolkit_configs.slug
                FROM agent_toolkits
                JOIN toolkit_configs
                  ON toolkit_configs.id = agent_toolkits.toolkit_id
                WHERE toolkit_configs.owner_agent_id IS NULL
                UNION ALL
                SELECT owner_agent_id AS agent_id, slug
                FROM toolkit_configs
                WHERE owner_agent_id IS NOT NULL
            ),
            duplicate_groups AS (
                SELECT
                    CASE
                        WHEN owner_agent_id IS NULL THEN workspace_id
                        ELSE owner_agent_id
                    END AS scope_id,
                    owner_agent_id IS NULL AS shared,
                    slug
                FROM toolkit_configs
                GROUP BY scope_id, shared, slug
                HAVING count(*) > 1
                UNION ALL
                SELECT agent_id AS scope_id, FALSE AS shared, slug
                FROM effective_toolkits
                GROUP BY agent_id, slug
                HAVING count(*) > 1
            )
            SELECT 1
            FROM duplicate_groups
            LIMIT 1
            """
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot recreate Toolkit Slug unique indexes while duplicate ownership "
            "or effective Slugs exist."
        )
    op.create_index(
        "uq_toolkit_configs_shared_workspace_slug",
        "toolkit_configs",
        ["workspace_id", "slug"],
        unique=True,
        postgresql_where=sa.text("owner_agent_id IS NULL"),
    )
    op.create_index(
        "uq_toolkit_configs_owner_agent_slug",
        "toolkit_configs",
        ["owner_agent_id", "slug"],
        unique=True,
        postgresql_where=sa.text("owner_agent_id IS NOT NULL"),
    )
