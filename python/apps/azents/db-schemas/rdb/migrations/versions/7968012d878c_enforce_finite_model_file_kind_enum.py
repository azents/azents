"""enforce finite model file kind enum

Revision ID: 7968012d878c
Revises: 3ac042ea72bd
Create Date: 2026-11-07 22:12:37.953959

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM

# revision identifiers, used by Alembic.
revision: str = "7968012d878c"
down_revision: str | Sequence[str] | None = "3ac042ea72bd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Preserve known classifications and reject unknown retained values."""
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM model_files
            WHERE kind NOT IN ('image', 'document', 'text', 'binary')
          ) THEN
            RAISE EXCEPTION 'Unsupported retained ModelFile kind';
          END IF;
        END
        $$;
        """
    )
    kinds = ENUM("image", "document", "text", "binary", name="model_file_kind")
    kinds.create(op.get_bind(), checkfirst=False)
    op.alter_column(
        "model_files",
        "kind",
        existing_type=sa.String(32),
        type_=kinds,
        existing_nullable=False,
        postgresql_using="kind::text::model_file_kind",
    )


def downgrade() -> None:
    """Restore the previous string storage without changing any values."""
    op.alter_column(
        "model_files",
        "kind",
        existing_type=ENUM(
            "image", "document", "text", "binary", name="model_file_kind"
        ),
        type_=sa.String(32),
        existing_nullable=False,
        postgresql_using="kind::text",
    )
    ENUM(name="model_file_kind").drop(op.get_bind(), checkfirst=False)
