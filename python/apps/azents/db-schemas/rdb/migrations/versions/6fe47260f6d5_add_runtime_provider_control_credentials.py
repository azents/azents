"""add runtime provider control credentials

Revision ID: 6fe47260f6d5
Revises: 41c9f7fe1060
Create Date: 2026-07-22 14:21:30.100383

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from azents.rdb.types.datetime import TimeZoneDateTime

# revision identifiers, used by Alembic.
revision: str = "6fe47260f6d5"
down_revision: str | Sequence[str] | None = "41c9f7fe1060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENROLLMENT_GRANT_STATE = postgresql.ENUM(
    "issued",
    "consumed",
    "revoked",
    name="runtime_provider_enrollment_grant_state",
    create_type=False,
)
_CREDENTIAL_STATE = postgresql.ENUM(
    "active",
    "revoked",
    name="runtime_provider_credential_state",
    create_type=False,
)
_CONNECTION_STATUS = postgresql.ENUM(
    "connected",
    "disconnected",
    name="runtime_provider_connection_status",
    create_type=False,
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    for enum_type in (
        _ENROLLMENT_GRANT_STATE,
        _CREDENTIAL_STATE,
        _CONNECTION_STATUS,
    ):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "runtime_provider_enrollment_grants",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=32), nullable=False),
        sa.Column("verifier", sa.String(length=64), nullable=False),
        sa.Column("state", _ENROLLMENT_GRANT_STATE, nullable=False),
        sa.Column("expires_at", TimeZoneDateTime(), nullable=False),
        sa.Column("issued_by_user_id", sa.String(length=32), nullable=True),
        sa.Column("issued_by_source_id", sa.String(length=32), nullable=True),
        sa.Column("consumed_at", TimeZoneDateTime(), nullable=True),
        sa.Column("consumed_credential_id", sa.String(length=32), nullable=True),
        sa.Column("revoked_at", TimeZoneDateTime(), nullable=True),
        sa.Column("revoked_by_user_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(issued_by_user_id IS NOT NULL AND issued_by_source_id IS NULL) OR "
            "(issued_by_user_id IS NULL AND issued_by_source_id IS NOT NULL)",
            name="ck_runtime_provider_enrollment_grants_issuer",
        ),
        sa.ForeignKeyConstraint(
            ["issued_by_source_id"],
            ["runtime_provider_bootstrap_sources.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["issued_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["runtime_providers.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_runtime_provider_enrollment_grants_expires_at",
        "runtime_provider_enrollment_grants",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_provider_enrollment_grants_provider_state",
        "runtime_provider_enrollment_grants",
        ["provider_id", "state"],
        unique=False,
    )

    op.create_table(
        "runtime_provider_credentials",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=32), nullable=False),
        sa.Column("verifier", sa.String(length=64), nullable=False),
        sa.Column("state", _CREDENTIAL_STATE, nullable=False),
        sa.Column("expires_at", TimeZoneDateTime(), nullable=True),
        sa.Column("issued_grant_id", sa.String(length=32), nullable=False),
        sa.Column("last_used_at", TimeZoneDateTime(), nullable=True),
        sa.Column("revoked_at", TimeZoneDateTime(), nullable=True),
        sa.Column("revoked_by_user_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["issued_grant_id"],
            ["runtime_provider_enrollment_grants.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["runtime_providers.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_runtime_provider_credentials_expires_at",
        "runtime_provider_credentials",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_provider_credentials_provider_state",
        "runtime_provider_credentials",
        ["provider_id", "state"],
        unique=False,
    )

    op.create_table(
        "runtime_provider_connections",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=32), nullable=False),
        sa.Column("credential_id", sa.String(length=32), nullable=False),
        sa.Column("connection_id", sa.String(length=120), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("status", _CONNECTION_STATUS, nullable=False),
        sa.Column("reported_provider_type", sa.String(length=120), nullable=False),
        sa.Column("reported_protocol_version", sa.String(length=120), nullable=False),
        sa.Column("connected_at", TimeZoneDateTime(), nullable=False),
        sa.Column("last_heartbeat_at", TimeZoneDateTime(), nullable=False),
        sa.Column("disconnected_at", TimeZoneDateTime(), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["runtime_provider_credentials.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["runtime_providers.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            name="uq_runtime_provider_connections_connection_id",
        ),
        sa.UniqueConstraint(
            "provider_id",
            "generation",
            name="uq_runtime_provider_connections_provider_generation",
        ),
    )
    op.create_index(
        "ix_runtime_provider_connections_credential_status",
        "runtime_provider_connections",
        ["credential_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_provider_connections_provider_status",
        "runtime_provider_connections",
        ["provider_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("runtime_provider_connections")
    op.drop_table("runtime_provider_credentials")
    op.drop_table("runtime_provider_enrollment_grants")

    bind = op.get_bind()
    for enum_type in (
        _CONNECTION_STATUS,
        _CREDENTIAL_STATE,
        _ENROLLMENT_GRANT_STATE,
    ):
        enum_type.drop(bind, checkfirst=True)
