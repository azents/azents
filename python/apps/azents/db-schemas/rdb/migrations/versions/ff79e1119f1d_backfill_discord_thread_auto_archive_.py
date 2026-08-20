"""Backfill Discord Thread automatic archive duration."""

from typing import Sequence

from alembic import op

revision: str = "ff79e1119f1d"
down_revision: str | Sequence[str] | None = "d0e25b8b7f90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Backfill every Discord connection to the one-day default."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM external_channel_connections
                WHERE provider = 'discord'
                  AND (
                      provider_config IS NULL
                      OR jsonb_typeof(provider_config) <> 'object'
                      OR NOT provider_config ? 'target_guild_id'
                  )
            ) THEN
                RAISE EXCEPTION
                    'Discord connection provider_config is missing target_guild_id';
            END IF;
        END
        $$;

        UPDATE external_channel_connections
        SET provider_config = provider_config || jsonb_build_object(
            'thread_auto_archive_duration_minutes',
            1440
        )
        WHERE provider = 'discord'
        """
    )


def downgrade() -> None:
    """Remove the Discord Thread automatic archive duration field."""
    op.execute(
        """
        UPDATE external_channel_connections
        SET provider_config =
            provider_config - 'thread_auto_archive_duration_minutes'
        WHERE provider = 'discord'
          AND provider_config IS NOT NULL
        """
    )
