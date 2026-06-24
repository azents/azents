"""migrate image_generation column to metadata supported_builtin_tools.

Revision ID: c803e4022946
Revises: 8b78cef0968b
Create Date: 2026-03-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "c803e4022946"
down_revision: str | Sequence[str] | None = "8b78cef0968b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# References the llm_provider_models table
t = sa.table(
    "llm_provider_models",
    sa.column("id", sa.String),
    sa.column("image_generation", sa.Boolean),
    sa.column("metadata", JSONB),
)


def upgrade() -> None:
    """Add image_generation to metadata.supported_builtin_tools where set.

    Then remove the image_generation column.
    """
    conn = op.get_bind()

    # Find records where image_generation=True
    rows = conn.execute(
        sa.select(t.c.id, t.c.metadata).where(t.c.image_generation.is_(True))
    ).fetchall()

    for row_id, metadata in rows:
        meta = dict(metadata) if metadata else {}
        supported: list[str] = list(meta.get("supported_builtin_tools", []))
        if "image_generation" not in supported:
            supported.append("image_generation")
        meta["supported_builtin_tools"] = supported

        conn.execute(sa.update(t).where(t.c.id == row_id).values(metadata=meta))

    # Drop image_generation column
    op.drop_column("llm_provider_models", "image_generation")


def downgrade() -> None:
    """Restore the image_generation column and revert values from metadata."""
    op.add_column(
        "llm_provider_models",
        sa.Column(
            "image_generation",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
    )

    conn = op.get_bind()

    # Restore records whose metadata.supported_builtin_tools includes 'image_generation'
    rows = conn.execute(
        sa.select(t.c.id, t.c.metadata).where(t.c.metadata.isnot(None))
    ).fetchall()

    for row_id, metadata in rows:
        meta = dict(metadata) if metadata else {}
        supported: list[str] = list(meta.get("supported_builtin_tools", []))
        if "image_generation" in supported:
            conn.execute(
                sa.update(t).where(t.c.id == row_id).values(image_generation=True)
            )
            supported.remove("image_generation")
            if supported:
                meta["supported_builtin_tools"] = supported
            else:
                meta.pop("supported_builtin_tools", None)
            conn.execute(sa.update(t).where(t.c.id == row_id).values(metadata=meta))
