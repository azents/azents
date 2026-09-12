"""allow runtime web approval beyond transport

Revision ID: 07f7858f8d36
Revises: 517e2d4e4fbf
Create Date: 2026-09-12 22:16:42.346517

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "07f7858f8d36"
down_revision: str | Sequence[str] | None = "517e2d4e4fbf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(
        "ck_runtime_web_tunnel_routes_deadlines",
        "runtime_web_tunnel_routes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_runtime_web_tunnel_routes_deadlines",
        "runtime_web_tunnel_routes",
        sa.text(
            "registration_deadline_at <= transport_deadline_at "
            "AND lease_expires_at <= transport_deadline_at"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "ck_runtime_web_tunnel_routes_deadlines",
        "runtime_web_tunnel_routes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_runtime_web_tunnel_routes_deadlines",
        "runtime_web_tunnel_routes",
        sa.text(
            "registration_deadline_at <= transport_deadline_at "
            "AND approval_deadline_at <= transport_deadline_at "
            "AND lease_expires_at <= transport_deadline_at"
        ),
    )
