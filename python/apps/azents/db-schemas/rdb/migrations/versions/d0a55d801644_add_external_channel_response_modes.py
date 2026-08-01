"""Add External Channel response modes."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d0a55d801644"
down_revision: str | Sequence[str] | None = "c67332e97043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RESPONSE_MODE = sa.Enum(
    "mention_only",
    "all_messages",
    name="external_channel_response_mode",
)
_RESPONSE_MODE_COLUMN = postgresql.ENUM(
    "mention_only",
    "all_messages",
    name="external_channel_response_mode",
    create_type=False,
)


def upgrade() -> None:
    """Add required Agent defaults and concrete binding response modes."""
    _RESPONSE_MODE.create(op.get_bind())
    op.add_column(
        "agents",
        sa.Column(
            "external_channel_default_response_mode",
            _RESPONSE_MODE_COLUMN,
            server_default="all_messages",
            nullable=False,
        ),
    )
    op.add_column(
        "external_channel_bindings",
        sa.Column(
            "response_mode",
            _RESPONSE_MODE_COLUMN,
            server_default="all_messages",
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Remove External Channel response modes."""
    op.drop_column("external_channel_bindings", "response_mode")
    op.drop_column("agents", "external_channel_default_response_mode")
    _RESPONSE_MODE.drop(op.get_bind())
