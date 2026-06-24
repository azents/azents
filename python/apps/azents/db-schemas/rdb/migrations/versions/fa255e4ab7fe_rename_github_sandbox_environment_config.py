"""rename github sandbox environment config

Revision ID: fa255e4ab7fe
Revises: 5e5e29f05ccf
Create Date: 2026-05-24 19:52:02.127346

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fa255e4ab7fe"
down_revision: str | Sequence[str] | None = "5e5e29f05ccf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Migrate to the GitHub toolkit sandbox environment config key."""
    op.execute(
        """
        UPDATE toolkit_configs
        SET config = (
            config
            - 'inject_shell_env'
            - 'inject_sandbox_setting'
        ) || jsonb_build_object(
            'inject_sandbox_environment',
            COALESCE(
                config->'inject_sandbox_environment',
                config->'inject_shell_env',
                config->'inject_sandbox_setting'
            )
        )
        WHERE toolkit_type = 'github'
          AND (
            config ? 'inject_sandbox_environment'
            OR config ? 'inject_shell_env'
            OR config ? 'inject_sandbox_setting'
          )
        """
    )


def downgrade() -> None:
    """Revert the GitHub toolkit config key to the previous shell env name."""
    op.execute(
        """
        UPDATE toolkit_configs
        SET config = (
            config - 'inject_sandbox_environment'
        ) || jsonb_build_object(
            'inject_shell_env',
            config->'inject_sandbox_environment'
        )
        WHERE toolkit_type = 'github'
          AND config ? 'inject_sandbox_environment'
        """
    )
