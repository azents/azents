"""Add durable Runtime Control connection-generation authority schema.

Revision ID: fa67b82b0b53
Revises: 39f7b371c71d
Create Date: 2026-09-07 15:57:06.916054
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from azents.rdb.types.datetime import TimeZoneDateTime

revision: str = "fa67b82b0b53"
down_revision: str | Sequence[str] | None = "39f7b371c71d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONNECTION_KIND = postgresql.ENUM(
    "provider",
    "runner",
    name="runtime_connection_authority_kind",
    create_type=False,
)
_INTEGER_MAX = 2**31 - 1


def upgrade() -> None:
    """Upgrade schema without activating the new allocator."""
    bind = op.get_bind()
    op.alter_column(
        "runtime_provider_connections",
        "generation",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )
    op.alter_column(
        "agent_runtimes",
        "provider_generation",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
        existing_server_default="0",
    )
    op.alter_column(
        "agent_runtimes",
        "runner_generation",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
        existing_server_default="0",
    )

    _CONNECTION_KIND.create(bind, checkfirst=True)
    op.create_table(
        "runtime_connection_generation_cutovers",
        sa.Column("allocator_version", sa.SmallInteger(), nullable=False),
        sa.Column("cutover_at", TimeZoneDateTime(), nullable=False),
        sa.CheckConstraint(
            "allocator_version > 0",
            name="ck_runtime_connection_generation_cutovers_positive_version",
        ),
        sa.PrimaryKeyConstraint("allocator_version"),
    )
    op.create_table(
        "runtime_connection_generations",
        sa.Column("connection_kind", _CONNECTION_KIND, nullable=False),
        sa.Column("subject_id", sa.String(length=32), nullable=False),
        sa.Column("high_water_generation", sa.BigInteger(), nullable=False),
        sa.Column("accepted_generation", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "accepted_generation <= high_water_generation",
            name="ck_runtime_connection_generations_accepted_within_high_water",
        ),
        sa.CheckConstraint(
            "high_water_generation >= 0 AND accepted_generation >= 0",
            name="ck_runtime_connection_generations_non_negative",
        ),
        sa.PrimaryKeyConstraint("connection_kind", "subject_id"),
    )


def downgrade() -> None:
    """Downgrade schema when no post-cutover generation has been persisted."""
    bind = op.get_bind()
    maxima = bind.execute(
        sa.text(
            """
            SELECT
              COALESCE((SELECT MAX(generation) FROM runtime_provider_connections), 0),
              COALESCE((SELECT MAX(provider_generation) FROM agent_runtimes), 0),
              COALESCE((SELECT MAX(runner_generation) FROM agent_runtimes), 0)
            """
        )
    ).one()
    if any(int(value) > _INTEGER_MAX for value in maxima):
        raise RuntimeError(
            "irreversible: post-cutover Runtime connection generation exceeds INTEGER"
        )

    op.drop_table("runtime_connection_generations")
    op.drop_table("runtime_connection_generation_cutovers")
    _CONNECTION_KIND.drop(bind, checkfirst=True)

    op.alter_column(
        "agent_runtimes",
        "runner_generation",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
        existing_server_default="0",
    )
    op.alter_column(
        "agent_runtimes",
        "provider_generation",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
        existing_server_default="0",
    )
    op.alter_column(
        "runtime_provider_connections",
        "generation",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
