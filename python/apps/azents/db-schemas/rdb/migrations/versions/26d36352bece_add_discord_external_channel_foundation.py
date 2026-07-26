"""add discord external channel foundation

Revision ID: 26d36352bece
Revises: cc31dfa97a1b
Create Date: 2026-07-26 06:22:31.819724

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "26d36352bece"
down_revision: str | Sequence[str] | None = "cc31dfa97a1b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_INGRESS_PROFILE_ENUM = postgresql.ENUM(
    "slack_http",
    "slack_socket",
    "discord_gateway_http",
    name="external_channel_ingress_profile",
    create_type=False,
)
_RESOURCE_PROVISIONING_OPERATION_ENUM = postgresql.ENUM(
    "thread_create",
    name="external_channel_resource_provisioning_operation",
    create_type=False,
)
_RESOURCE_PROVISIONING_STATUS_ENUM = postgresql.ENUM(
    "pending",
    "attempting",
    "delivered",
    "failed",
    "unknown",
    name="external_channel_resource_provisioning_status",
    create_type=False,
)
_WORK_PROJECTION_STATUS_ENUM = postgresql.ENUM(
    "pending",
    "present",
    "failed",
    "unknown",
    "deleted",
    name="external_channel_work_projection_status",
    create_type=False,
)


def _create_enum_types() -> None:
    """Create PostgreSQL enum types owned by this revision."""
    bind = op.get_bind()
    for enum_type in (
        _INGRESS_PROFILE_ENUM,
        _RESOURCE_PROVISIONING_OPERATION_ENUM,
        _RESOURCE_PROVISIONING_STATUS_ENUM,
        _WORK_PROJECTION_STATUS_ENUM,
    ):
        enum_type.create(bind)


def _drop_enum_types() -> None:
    """Drop PostgreSQL enum types owned by this revision."""
    bind = op.get_bind()
    for enum_type in (
        _WORK_PROJECTION_STATUS_ENUM,
        _RESOURCE_PROVISIONING_STATUS_ENUM,
        _RESOURCE_PROVISIONING_OPERATION_ENUM,
        _INGRESS_PROFILE_ENUM,
    ):
        enum_type.drop(bind)


def upgrade() -> None:
    """Add durable Discord provider foundations without activating ingress."""
    op.execute("ALTER TYPE external_channel_provider ADD VALUE IF NOT EXISTS 'discord'")
    _create_enum_types()

    op.add_column(
        "external_channel_connections",
        sa.Column("ingress_profile", _INGRESS_PROFILE_ENUM, nullable=True),
    )
    op.add_column(
        "external_channel_connections",
        sa.Column(
            "configuration_generation",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.execute(
        """
        UPDATE external_channel_connections
        SET ingress_profile = CASE transport
            WHEN 'socket' THEN 'slack_socket'::external_channel_ingress_profile
            ELSE 'slack_http'::external_channel_ingress_profile
        END
        WHERE ingress_profile IS NULL
        """
    )
    op.alter_column(
        "external_channel_connections",
        "ingress_profile",
        nullable=False,
    )
    op.drop_index(
        "uq_external_channel_connections_installation_identity",
        table_name="external_channel_connections",
    )
    op.create_index(
        "uq_external_channel_connections_installation_identity",
        "external_channel_connections",
        ["provider", "provider_tenant_id", "provider_app_id"],
        unique=True,
        postgresql_where=sa.text(
            "provider = 'slack' "
            "AND provider_tenant_id IS NOT NULL "
            "AND provider_app_id IS NOT NULL"
        ),
    )

    op.create_table(
        "external_channel_app_claims",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "provider",
            postgresql.ENUM(
                name="external_channel_provider",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("provider_app_id", sa.String(length=255), nullable=False),
        sa.Column("connection_id", sa.String(length=32), nullable=False),
        sa.Column(
            "claim_generation",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "acquired_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["external_channel_connections.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "provider_app_id",
            name="uq_external_channel_app_claims_provider_app_id",
        ),
    )
    op.create_index(
        "ix_external_channel_app_claims_connection_id",
        "external_channel_app_claims",
        ["connection_id"],
        unique=False,
    )

    op.create_table(
        "external_channel_ingress_leases",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("connection_id", sa.String(length=32), nullable=False),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column(
            "lease_generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "required_configuration_generation",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column("required_app_claim_generation", sa.Integer(), nullable=True),
        sa.Column("gap_detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gap_reason", sa.String(length=255), nullable=True),
        sa.Column("encrypted_checkpoint", sa.Text(), nullable=True),
        sa.Column("checkpoint_version", sa.Integer(), nullable=True),
        sa.Column("last_handled_dispatch_sequence", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["external_channel_connections.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            name="uq_external_channel_ingress_leases_connection_id",
        ),
    )
    op.create_index(
        "ix_external_channel_ingress_leases_lease_until",
        "external_channel_ingress_leases",
        ["lease_until"],
        unique=False,
    )

    op.create_table(
        "external_channel_resource_provisionings",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.String(length=32), nullable=False),
        sa.Column("conversation_admission_id", sa.String(length=32), nullable=False),
        sa.Column(
            "operation",
            _RESOURCE_PROVISIONING_OPERATION_ENUM,
            nullable=False,
        ),
        sa.Column(
            "target_provider_resource_key",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "status",
            _RESOURCE_PROVISIONING_STATUS_ENUM,
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "confirmed_provider_resource_key",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column("error_kind", sa.String(length=120), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["external_channel_resources.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_admission_id"],
            ["external_channel_conversation_admissions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "resource_id",
            "conversation_admission_id",
            "operation",
            name=("uq_ec_resource_provisionings_admission_operation"),
        ),
    )
    op.create_index(
        "ix_external_channel_resource_provisionings_status_created_at",
        "external_channel_resource_provisionings",
        ["status", "created_at"],
        unique=False,
    )

    op.add_column(
        "external_channel_delivery_attempts",
        sa.Column(
            "part_ordinal",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.execute(
        "UPDATE external_channel_delivery_attempts "
        "SET part_ordinal = 0 WHERE part_ordinal IS NULL"
    )
    op.drop_index(
        "uq_external_channel_delivery_attempts_operation_with_binding",
        table_name="external_channel_delivery_attempts",
    )
    op.drop_index(
        "uq_external_channel_delivery_attempts_operation_without_binding",
        table_name="external_channel_delivery_attempts",
    )
    op.create_index(
        "uq_external_channel_delivery_attempts_operation_with_binding",
        "external_channel_delivery_attempts",
        ["origin_type", "origin_id", "binding_id", "operation", "part_ordinal"],
        unique=True,
        postgresql_where=sa.text("binding_id IS NOT NULL"),
    )
    op.create_index(
        "uq_external_channel_delivery_attempts_operation_without_binding",
        "external_channel_delivery_attempts",
        ["origin_type", "origin_id", "operation", "part_ordinal"],
        unique=True,
        postgresql_where=sa.text("binding_id IS NULL"),
    )

    op.create_table(
        "external_channel_work_projection_parts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("work_id", sa.String(length=32), nullable=False),
        sa.Column("part_ordinal", sa.Integer(), nullable=False),
        sa.Column("desired_progress_revision", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            _WORK_PROJECTION_STATUS_ENUM,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("provider_message_key", sa.String(length=255), nullable=True),
        sa.Column("latest_delivery_attempt_id", sa.String(length=32), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["work_id"],
            ["external_channel_works.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["latest_delivery_attempt_id"],
            ["external_channel_delivery_attempts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "work_id",
            "part_ordinal",
            name="uq_external_channel_work_projection_parts_work_part_ordinal",
        ),
    )
    op.create_index(
        "ix_external_channel_work_projection_parts_status_updated_at",
        "external_channel_work_projection_parts",
        ["status", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove Discord foundation records after proving no Discord state remains."""
    bind = op.get_bind()
    for table_name in (
        "external_channel_app_claims",
        "external_channel_ingress_leases",
        "external_channel_resource_provisionings",
        "external_channel_work_projection_parts",
    ):
        if bind.scalar(sa.text(f"SELECT count(*) FROM {table_name}")):
            raise RuntimeError(
                f"Cannot remove Discord foundation while {table_name} has rows."
            )
    for table_name in (
        "external_channel_connections",
        "external_channel_principals",
    ):
        if bind.scalar(
            sa.text(f"SELECT count(*) FROM {table_name} WHERE provider = 'discord'")
        ):
            raise RuntimeError(
                "Cannot remove Discord foundation while Discord provider rows exist."
            )

    op.drop_index(
        "ix_external_channel_work_projection_parts_status_updated_at",
        table_name="external_channel_work_projection_parts",
    )
    op.drop_table("external_channel_work_projection_parts")
    op.drop_index(
        "uq_external_channel_delivery_attempts_operation_with_binding",
        table_name="external_channel_delivery_attempts",
    )
    op.drop_index(
        "uq_external_channel_delivery_attempts_operation_without_binding",
        table_name="external_channel_delivery_attempts",
    )
    op.create_index(
        "uq_external_channel_delivery_attempts_operation_with_binding",
        "external_channel_delivery_attempts",
        ["origin_type", "origin_id", "binding_id", "operation"],
        unique=True,
        postgresql_where=sa.text("binding_id IS NOT NULL"),
    )
    op.create_index(
        "uq_external_channel_delivery_attempts_operation_without_binding",
        "external_channel_delivery_attempts",
        ["origin_type", "origin_id", "operation"],
        unique=True,
        postgresql_where=sa.text("binding_id IS NULL"),
    )
    op.drop_column("external_channel_delivery_attempts", "part_ordinal")

    op.drop_index(
        "ix_external_channel_resource_provisionings_status_created_at",
        table_name="external_channel_resource_provisionings",
    )
    op.drop_table("external_channel_resource_provisionings")
    op.drop_index(
        "ix_external_channel_ingress_leases_lease_until",
        table_name="external_channel_ingress_leases",
    )
    op.drop_table("external_channel_ingress_leases")
    op.drop_index(
        "ix_external_channel_app_claims_connection_id",
        table_name="external_channel_app_claims",
    )
    op.drop_table("external_channel_app_claims")

    op.drop_index(
        "uq_external_channel_connections_installation_identity",
        table_name="external_channel_connections",
    )
    op.create_index(
        "uq_external_channel_connections_installation_identity",
        "external_channel_connections",
        ["provider", "provider_tenant_id", "provider_app_id"],
        unique=True,
        postgresql_where=sa.text(
            "provider_tenant_id IS NOT NULL AND provider_app_id IS NOT NULL"
        ),
    )
    op.drop_column("external_channel_connections", "configuration_generation")
    op.drop_column("external_channel_connections", "ingress_profile")
    _drop_enum_types()

    for table_name in (
        "external_channel_connections",
        "external_channel_principals",
    ):
        op.execute(
            sa.text(
                f"ALTER TABLE {table_name} "
                "ALTER COLUMN provider TYPE varchar(20) USING provider::text"
            )
        )
    op.execute("DROP TYPE external_channel_provider")
    op.execute("CREATE TYPE external_channel_provider AS ENUM ('slack')")
    for table_name in (
        "external_channel_connections",
        "external_channel_principals",
    ):
        op.execute(
            sa.text(
                f"ALTER TABLE {table_name} ALTER COLUMN provider "
                "TYPE external_channel_provider "
                "USING provider::external_channel_provider"
            )
        )
