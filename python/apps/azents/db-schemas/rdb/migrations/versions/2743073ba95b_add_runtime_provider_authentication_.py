"""add runtime provider authentication bindings

Revision ID: 2743073ba95b
Revises: ae769da63fed
Create Date: 2026-07-23 15:18:58.655928

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from azents.rdb.types.datetime import TimeZoneDateTime

revision: str = "2743073ba95b"
down_revision: str | Sequence[str] | None = "ae769da63fed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    binding_state = postgresql.ENUM(
        "active", "revoked", name="runtime_provider_binding_state", create_type=False
    )
    binding_owner = postgresql.ENUM(
        "admin", "bootstrap", name="runtime_provider_binding_owner", create_type=False
    )
    auth_method = postgresql.ENUM(
        "azents_issued_token",
        "kubernetes_service_account",
        name="runtime_provider_auth_method",
        create_type=False,
    )
    binding_audit_event_type = postgresql.ENUM(
        "created",
        "reconciled",
        "authenticated",
        "connected",
        "rotated",
        "revoked",
        "conflict",
        name="runtime_provider_binding_audit_event_type",
        create_type=False,
    )
    for enum_type in (
        binding_state,
        binding_owner,
        auth_method,
        binding_audit_event_type,
    ):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "runtime_provider_auth_bindings",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=32), nullable=False),
        sa.Column("auth_method", auth_method, nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("state", binding_state, nullable=False),
        sa.Column("owner", binding_owner, nullable=False),
        sa.Column("bootstrap_declaration_id", sa.String(length=32), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "admin_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("last_authenticated_at", TimeZoneDateTime(), nullable=True),
        sa.Column("last_connected_at", TimeZoneDateTime(), nullable=True),
        sa.Column("revoked_at", TimeZoneDateTime(), nullable=True),
        sa.Column("revoked_by_user_id", sa.String(length=32), nullable=True),
        sa.Column("revocation_reason", sa.String(length=255), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["bootstrap_declaration_id"],
            ["runtime_provider_bootstrap_declarations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["runtime_providers.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_runtime_provider_auth_bindings_method_subject_active",
        "runtime_provider_auth_bindings",
        ["auth_method", "subject"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )
    op.create_index(
        "uq_runtime_provider_auth_bindings_bootstrap_declaration_active",
        "runtime_provider_auth_bindings",
        ["bootstrap_declaration_id"],
        unique=True,
        postgresql_where=sa.text(
            "state = 'active' AND bootstrap_declaration_id IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_runtime_provider_auth_bindings_provider_state",
        "runtime_provider_auth_bindings",
        ["provider_id", "state"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_provider_auth_bindings_method_subject_state",
        "runtime_provider_auth_bindings",
        ["auth_method", "subject", "state"],
        unique=False,
    )
    op.create_table(
        "runtime_provider_auth_binding_audit_events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("binding_id", sa.String(length=32), nullable=False),
        sa.Column("event_type", binding_audit_event_type, nullable=False),
        sa.Column("actor_user_id", sa.String(length=32), nullable=True),
        sa.Column("previous_admin_version", sa.Integer(), nullable=True),
        sa.Column("new_admin_version", sa.Integer(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["runtime_provider_auth_bindings.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_runtime_provider_auth_binding_audit_events_binding_created",
        "runtime_provider_auth_binding_audit_events",
        ["binding_id", "created_at"],
        unique=False,
    )

    op.add_column(
        "runtime_provider_enrollment_grants",
        sa.Column("binding_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "runtime_provider_credentials",
        sa.Column("binding_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "runtime_provider_connections",
        sa.Column("binding_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "runtime_provider_connections",
        sa.Column(
            "auth_method",
            auth_method,
            server_default=sa.text("'azents_issued_token'"),
            nullable=False,
        ),
    )
    op.add_column(
        "runtime_provider_connections",
        sa.Column(
            "auth_subject",
            sa.String(length=255),
            nullable=True,
        ),
    )
    op.add_column(
        "runtime_provider_connections",
        sa.Column(
            "evidence_expires_at",
            TimeZoneDateTime(),
            nullable=True,
        ),
    )
    op.alter_column(
        "runtime_provider_connections",
        "credential_id",
        existing_type=sa.String(length=32),
        nullable=True,
    )

    bind.execute(
        sa.text("""
        INSERT INTO runtime_provider_auth_bindings (
            id,
            provider_id,
            auth_method,
            subject,
            state,
            owner,
            bootstrap_declaration_id,
            config
        )
        SELECT DISTINCT
            md5(
                enrollment.provider_id
                || CASE
                    WHEN enrollment.issued_by_source_id IS NULL THEN ':' || 'admin'
                    ELSE ':' || 'bootstrap' || ':' || enrollment.issued_by_source_id
                END
            ),
            enrollment.provider_id,
            CAST('azents_issued_token' AS runtime_provider_auth_method),
            'provider:' || enrollment.provider_id
                || CASE
                    WHEN enrollment.issued_by_source_id IS NULL THEN ':' || 'admin'
                    ELSE ':' || 'bootstrap' || ':' || enrollment.issued_by_source_id
                END,
            CAST('active' AS runtime_provider_binding_state),
            CASE
                WHEN enrollment.issued_by_source_id IS NULL
                    THEN CAST('admin' AS runtime_provider_binding_owner)
                ELSE CAST('bootstrap' AS runtime_provider_binding_owner)
            END,
            declaration.id,
            jsonb_build_object(
                'migration', '2743073ba95b',
                'issuer', CASE
                    WHEN enrollment.issued_by_source_id IS NULL THEN 'admin'
                    ELSE 'bootstrap'
                END
            )
        FROM runtime_provider_enrollment_grants AS enrollment
        LEFT JOIN runtime_provider_bootstrap_declarations AS declaration
            ON declaration.provider_id = enrollment.provider_id
            AND declaration.source_id = enrollment.issued_by_source_id
    """)
    )
    bind.execute(
        sa.text("""
        UPDATE runtime_provider_enrollment_grants AS enrollment
        SET binding_id = binding.id
        FROM runtime_provider_auth_bindings AS binding
        WHERE binding.provider_id = enrollment.provider_id
          AND binding.auth_method = 'azents_issued_token'
          AND binding.subject = (
              'provider:' || enrollment.provider_id
              || CASE
                  WHEN enrollment.issued_by_source_id IS NULL THEN ':' || 'admin'
                  ELSE ':' || 'bootstrap' || ':' || enrollment.issued_by_source_id
              END
          )
    """)
    )
    bind.execute(
        sa.text("""
        UPDATE runtime_provider_credentials AS credential
        SET binding_id = enrollment.binding_id
        FROM runtime_provider_enrollment_grants AS enrollment
        WHERE credential.issued_grant_id = enrollment.id
    """)
    )
    bind.execute(
        sa.text("""
        UPDATE runtime_provider_connections AS connection
        SET binding_id = credential.binding_id,
            auth_subject = binding.subject,
            evidence_expires_at = credential.expires_at
        FROM runtime_provider_credentials AS credential
        JOIN runtime_provider_auth_bindings AS binding
          ON binding.id = credential.binding_id
        WHERE connection.credential_id = credential.id
    """)
    )
    bind.execute(
        sa.text("""
        INSERT INTO runtime_provider_auth_binding_audit_events (
            id,
            binding_id,
            event_type,
            actor_user_id,
            previous_admin_version,
            new_admin_version,
            metadata
        )
        SELECT
            md5(binding.id || ':' || 'created'),
            binding.id,
            CAST('created' AS runtime_provider_binding_audit_event_type),
            NULL,
            NULL,
            binding.admin_version,
            jsonb_build_object('migration', '2743073ba95b')
        FROM runtime_provider_auth_bindings AS binding
    """)
    )

    for table in (
        "runtime_provider_enrollment_grants",
        "runtime_provider_credentials",
        "runtime_provider_connections",
    ):
        op.alter_column(
            table, "binding_id", existing_type=sa.String(length=32), nullable=False
        )
    op.alter_column(
        "runtime_provider_connections",
        "auth_method",
        existing_type=auth_method,
        server_default=None,
    )
    op.alter_column(
        "runtime_provider_connections",
        "auth_subject",
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_runtime_provider_enrollment_grants_binding_id",
        "runtime_provider_enrollment_grants",
        "runtime_provider_auth_bindings",
        ["binding_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_runtime_provider_credentials_binding_id",
        "runtime_provider_credentials",
        "runtime_provider_auth_bindings",
        ["binding_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_runtime_provider_connections_binding_id",
        "runtime_provider_connections",
        "runtime_provider_auth_bindings",
        ["binding_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_runtime_provider_connections_binding_status",
        "runtime_provider_connections",
        ["binding_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_runtime_provider_connections_binding_status",
        table_name="runtime_provider_connections",
    )
    for table, constraint in (
        ("runtime_provider_connections", "fk_runtime_provider_connections_binding_id"),
        ("runtime_provider_credentials", "fk_runtime_provider_credentials_binding_id"),
        (
            "runtime_provider_enrollment_grants",
            "fk_runtime_provider_enrollment_grants_binding_id",
        ),
    ):
        op.drop_constraint(constraint, table, type_="foreignkey")
    op.drop_column("runtime_provider_connections", "evidence_expires_at")
    op.drop_column("runtime_provider_connections", "auth_subject")
    op.drop_column("runtime_provider_connections", "auth_method")
    op.drop_column("runtime_provider_connections", "binding_id")
    op.drop_column("runtime_provider_credentials", "binding_id")
    op.drop_column("runtime_provider_enrollment_grants", "binding_id")
    op.drop_table("runtime_provider_auth_binding_audit_events")
    op.drop_index(
        "uq_runtime_provider_auth_bindings_method_subject_active",
        table_name="runtime_provider_auth_bindings",
    )
    op.drop_index(
        "uq_runtime_provider_auth_bindings_bootstrap_declaration_active",
        table_name="runtime_provider_auth_bindings",
    )
    op.drop_table("runtime_provider_auth_bindings")
    bind = op.get_bind()
    for enum_name in (
        "runtime_provider_binding_audit_event_type",
        "runtime_provider_auth_method",
        "runtime_provider_binding_owner",
        "runtime_provider_binding_state",
    ):
        bind.execute(sa.text(f"DROP TYPE IF EXISTS {enum_name}"))
