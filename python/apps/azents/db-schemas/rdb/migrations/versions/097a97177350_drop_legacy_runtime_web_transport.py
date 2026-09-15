"""Drop legacy Runtime Web transport."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "097a97177350"
down_revision: str | Sequence[str] | None = "eebc06bf6bf0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove drained request-scoped Runtime Web transport state."""
    op.execute(
        sa.text(
            """
            LOCK TABLE
                runtime_web_gateway_admission_leases,
                runtime_web_admission_leases,
                runtime_web_tunnel_routes
            IN ACCESS EXCLUSIVE MODE
            """
        )
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM runtime_web_tunnel_routes
                    WHERE lease_expires_at > now()
                ) OR EXISTS (
                    SELECT 1
                    FROM runtime_web_admission_leases
                    WHERE lease_expires_at > now()
                ) OR EXISTS (
                    SELECT 1
                    FROM runtime_web_gateway_admission_leases
                    WHERE lease_expires_at > now()
                ) THEN
                    RAISE EXCEPTION
                        'Runtime Web maintenance preflight found active legacy work'
                        USING ERRCODE = '55006';
                END IF;
            END
            $$;
            """
        )
    )
    op.drop_table("runtime_web_gateway_admission_leases")
    op.drop_table("runtime_web_admission_leases")
    op.drop_table("runtime_web_tunnel_routes")


def downgrade() -> None:
    """Reject restoration of the removed request-scoped transport."""
    raise RuntimeError("Runtime Web clean cutover is irreversible and forward-only")
