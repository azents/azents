"""Preserve supported user locale values in a finite PostgreSQL domain."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM

revision: str = "aed428366a0a"
down_revision: str | Sequence[str] | None = "090e27a51823"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Reject unknown retained locales before the lossless type conversion."""
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM users
            WHERE locale NOT IN ('en-US', 'ko-KR', 'ja-JP', 'fr-FR')
          ) THEN
            RAISE EXCEPTION 'Unsupported retained user locale';
          END IF;
        END
        $$;
        """
    )
    locales = ENUM("en-US", "ko-KR", "ja-JP", "fr-FR", name="user_locale")
    locales.create(op.get_bind(), checkfirst=False)
    op.alter_column("users", "locale", server_default=None)
    op.alter_column(
        "users",
        "locale",
        existing_type=sa.String(35),
        type_=locales,
        existing_nullable=False,
        postgresql_using="locale::text::user_locale",
    )
    op.alter_column("users", "locale", server_default="en-US")


def downgrade() -> None:
    """Restore the original string domain and default without changing rows."""
    op.alter_column("users", "locale", server_default=None)
    op.alter_column(
        "users",
        "locale",
        existing_type=ENUM("en-US", "ko-KR", "ja-JP", "fr-FR", name="user_locale"),
        type_=sa.String(35),
        existing_nullable=False,
        postgresql_using="locale::text",
    )
    op.alter_column("users", "locale", server_default="en-US")
    ENUM(name="user_locale").drop(op.get_bind(), checkfirst=False)
