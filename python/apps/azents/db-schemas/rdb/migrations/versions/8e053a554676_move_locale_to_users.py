"""move locale to users

Revision ID: 8e053a554676
Revises: e7b9efaae7a5
Create Date: 2026-07-21 16:01:43.813473

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8e053a554676"
down_revision: str | Sequence[str] | None = "e7b9efaae7a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUPPORTED_LOCALES = ("en-US", "ko-KR", "ja-JP", "fr-FR")


def upgrade() -> None:
    """Move locale from workspace memberships to users."""
    op.add_column(
        "users",
        sa.Column(
            "locale",
            sa.String(length=35),
            nullable=False,
            server_default=sa.text("'en-US'"),
        ),
    )
    op.get_bind().execute(
        sa.text(
            """
            WITH earliest_memberships AS (
                SELECT DISTINCT ON (user_id) user_id, locale
                FROM workspace_users
                ORDER BY user_id, created_at ASC, id ASC
            )
            UPDATE users
            SET locale = CASE
                WHEN earliest_memberships.locale IN :supported_locales
                    THEN earliest_memberships.locale
                ELSE 'en-US'
            END
            FROM earliest_memberships
            WHERE users.id = earliest_memberships.user_id
            """
        ).bindparams(sa.bindparam("supported_locales", expanding=True)),
        {"supported_locales": SUPPORTED_LOCALES},
    )
    op.drop_column("workspace_users", "locale")


def downgrade() -> None:
    """Restore workspace membership locales from account locales."""
    op.add_column(
        "workspace_users",
        sa.Column(
            "locale",
            sa.String(length=35),
            nullable=False,
            server_default=sa.text("'en-US'"),
        ),
    )
    op.get_bind().execute(
        sa.text(
            """
            UPDATE workspace_users
            SET locale = users.locale
            FROM users
            WHERE workspace_users.user_id = users.id
            """
        )
    )
    op.drop_column("users", "locale")
