"""add model file run boundaries

Revision ID: 2c64d8eaf5b1
Revises: 19c8f7a6b2d4
Create Date: 2026-06-02 21:20:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2c64d8eaf5b1"
down_revision: str | Sequence[str] | None = "19c8f7a6b2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ModelFile creation and expiration run boundaries."""
    op.add_column(
        "model_files",
        sa.Column(
            "created_run_index",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
    )
    op.add_column(
        "model_files",
        sa.Column(
            "expires_after_run_index",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
    )
    op.alter_column("model_files", "created_run_index", server_default=None)
    op.alter_column("model_files", "expires_after_run_index", server_default=None)
    op.create_index(
        "ix_model_files_expiration",
        "model_files",
        ["session_id", "status", "expires_after_run_index"],
    )


def downgrade() -> None:
    """Remove ModelFile creation and expiration run boundaries."""
    op.drop_index("ix_model_files_expiration", table_name="model_files")
    op.drop_column("model_files", "expires_after_run_index")
    op.drop_column("model_files", "created_run_index")
