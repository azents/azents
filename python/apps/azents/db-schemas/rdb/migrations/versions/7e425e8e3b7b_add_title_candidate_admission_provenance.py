"""add title candidate admission provenance

Revision ID: 7e425e8e3b7b
Revises: fc4b83f4fe17
Create Date: 2026-08-02 17:51:02.557528

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7e425e8e3b7b"
down_revision: str | Sequence[str] | None = "fc4b83f4fe17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add immutable admission provenance to title candidates."""
    op.add_column(
        "external_channel_session_title_candidates",
        sa.Column("admission_access_request_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "external_channel_session_title_candidates",
        sa.Column("admission_provisional_title", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_ec_session_title_candidates_admission_access_request",
        "external_channel_session_title_candidates",
        "external_channel_access_requests",
        ["admission_access_request_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_ec_session_title_candidates_access_provisional_title",
        "external_channel_session_title_candidates",
        "admission_access_request_id IS NULL OR "
        "(admission_provisional_title IS NOT NULL "
        "AND length(btrim(admission_provisional_title)) > 0)",
    )


def downgrade() -> None:
    """Remove provenance only before it has been written."""
    unsafe = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM external_channel_session_title_candidates
                    WHERE admission_access_request_id IS NOT NULL
                       OR admission_provisional_title IS NOT NULL
                )
                """
            )
        )
        .scalar_one()
    )
    if unsafe:
        raise RuntimeError(
            "Cannot downgrade after External Channel title admission provenance "
            "is written."
        )
    op.drop_constraint(
        "ck_ec_session_title_candidates_access_provisional_title",
        "external_channel_session_title_candidates",
        type_="check",
    )
    op.drop_constraint(
        "fk_ec_session_title_candidates_admission_access_request",
        "external_channel_session_title_candidates",
        type_="foreignkey",
    )
    op.drop_column(
        "external_channel_session_title_candidates",
        "admission_provisional_title",
    )
    op.drop_column(
        "external_channel_session_title_candidates",
        "admission_access_request_id",
    )
