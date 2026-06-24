"""add input buffer client request id

Revision ID: ec89bacbbeb7
Revises: c1a587cbe77f
Create Date: 2026-06-05 06:34:23.598721

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ec89bacbbeb7"
down_revision: str | Sequence[str] | None = "c1a587cbe77f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the InputBuffer REST write idempotency key."""
    op.add_column(
        "input_buffers",
        sa.Column("client_request_id", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_input_buffers_runtime_user_client_request",
        "input_buffers",
        ["agent_runtime_id", "user_id", "client_request_id"],
    )


def downgrade() -> None:
    """Remove the InputBuffer REST write idempotency key."""
    op.drop_constraint(
        "uq_input_buffers_runtime_user_client_request",
        "input_buffers",
        type_="unique",
    )
    op.drop_column("input_buffers", "client_request_id")
