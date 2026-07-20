"""Add the provider-neutral System Settings persistence foundation.

Revision ID: ec609e0da8ab
Revises: c0a51320cfdb
Create Date: 2026-07-20 06:44:27.981638

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from azents.rdb.types.datetime import TimeZoneDateTime

revision: str = "ec609e0da8ab"
down_revision: str | Sequence[str] | None = "c0a51320cfdb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

system_setting_section = postgresql.ENUM(
    "platform_github_app",
    name="system_setting_section",
    create_type=False,
)
system_setting_validation_status = postgresql.ENUM(
    "pending",
    "valid",
    "invalid",
    "unavailable",
    name="system_setting_validation_status",
    create_type=False,
)
system_setting_health_status = postgresql.ENUM(
    "healthy",
    "invalid",
    "unavailable",
    name="system_setting_health_status",
    create_type=False,
)
system_setting_audit_event_type = postgresql.ENUM(
    "candidate_replaced",
    "candidate_validated",
    "candidate_cancelled",
    "activated",
    "health_checked",
    name="system_setting_audit_event_type",
    create_type=False,
)
system_setting_audit_source = postgresql.ENUM(
    "admin_api",
    "application_migration",
    "system",
    name="system_setting_audit_source",
    create_type=False,
)
system_data_migration_outcome = postgresql.ENUM(
    "applied",
    "skipped",
    name="system_data_migration_outcome",
    create_type=False,
)


def upgrade() -> None:
    """Create System Settings state, candidate, health, audit, and marker tables."""
    bind = op.get_bind()
    system_setting_section.create(bind, checkfirst=True)
    system_setting_validation_status.create(bind, checkfirst=True)
    system_setting_health_status.create(bind, checkfirst=True)
    system_setting_audit_event_type.create(bind, checkfirst=True)
    system_setting_audit_source.create(bind, checkfirst=True)
    system_data_migration_outcome.create(bind, checkfirst=True)

    op.create_table(
        "system_settings",
        sa.Column("section", system_setting_section, nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("encrypted_secrets", sa.Text(), nullable=True),
        sa.Column(
            "secret_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "validation_status",
            system_setting_validation_status,
            nullable=True,
        ),
        sa.Column("validated_generation", sa.String(length=64), nullable=True),
        sa.Column(
            "validation_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("validated_at", TimeZoneDateTime(), nullable=True),
        sa.Column("updated_by_user_id", sa.String(length=32), nullable=True),
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
            ["updated_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("section"),
    )
    op.create_index(
        "ix_system_settings_updated_by_user_id",
        "system_settings",
        ["updated_by_user_id"],
        unique=False,
    )

    op.create_table(
        "system_setting_candidates",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("section", system_setting_section, nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "validation_status",
            system_setting_validation_status,
            nullable=False,
        ),
        sa.Column("created_at", TimeZoneDateTime(), nullable=False),
        sa.Column("updated_at", TimeZoneDateTime(), nullable=False),
        sa.Column("expires_at", TimeZoneDateTime(), nullable=False),
        sa.Column("encrypted_secrets", sa.Text(), nullable=True),
        sa.Column(
            "secret_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("validated_generation", sa.String(length=64), nullable=True),
        sa.Column("validation_code", sa.String(length=120), nullable=True),
        sa.Column("validation_message", sa.Text(), nullable=True),
        sa.Column("action_hint", sa.Text(), nullable=True),
        sa.Column(
            "validation_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "impact",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("created_by_user_id", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "section",
            name="uq_system_setting_candidates_section",
        ),
    )
    op.create_index(
        "ix_system_setting_candidates_created_by_user_id",
        "system_setting_candidates",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_system_setting_candidates_expires_at",
        "system_setting_candidates",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "system_setting_health",
        sa.Column("section", system_setting_section, nullable=False),
        sa.Column("effective_generation", sa.String(length=64), nullable=False),
        sa.Column("status", system_setting_health_status, nullable=False),
        sa.Column("checked_at", TimeZoneDateTime(), nullable=False),
        sa.Column("code", sa.String(length=120), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("action_hint", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("checked_by_user_id", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["checked_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("section"),
    )
    op.create_index(
        "ix_system_setting_health_checked_by_user_id",
        "system_setting_health",
        ["checked_by_user_id"],
        unique=False,
    )

    op.create_table(
        "system_setting_audit_events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("section", system_setting_section, nullable=False),
        sa.Column("event_type", system_setting_audit_event_type, nullable=False),
        sa.Column("source", system_setting_audit_source, nullable=False),
        sa.Column(
            "changed_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "secret_actions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("impact_confirmed", sa.Boolean(), nullable=False),
        sa.Column("created_at", TimeZoneDateTime(), nullable=False),
        sa.Column("previous_version", sa.Integer(), nullable=True),
        sa.Column("new_version", sa.Integer(), nullable=True),
        sa.Column("actor_user_id", sa.String(length=32), nullable=True),
        sa.Column(
            "validation_status",
            system_setting_validation_status,
            nullable=True,
        ),
        sa.Column("candidate_id", sa.String(length=32), nullable=True),
        sa.Column("confirmation_action", sa.String(length=120), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_system_setting_audit_events_actor_user_id",
        "system_setting_audit_events",
        ["actor_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_system_setting_audit_events_section_created_at",
        "system_setting_audit_events",
        ["section", sa.literal_column("created_at DESC")],
        unique=False,
    )

    op.create_table(
        "system_data_migrations",
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("outcome", system_data_migration_outcome, nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("completed_at", TimeZoneDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    """Remove the provider-neutral System Settings persistence foundation."""
    op.drop_table("system_data_migrations")
    op.drop_index(
        "ix_system_setting_audit_events_section_created_at",
        table_name="system_setting_audit_events",
    )
    op.drop_index(
        "ix_system_setting_audit_events_actor_user_id",
        table_name="system_setting_audit_events",
    )
    op.drop_table("system_setting_audit_events")
    op.drop_index(
        "ix_system_setting_health_checked_by_user_id",
        table_name="system_setting_health",
    )
    op.drop_table("system_setting_health")
    op.drop_index(
        "ix_system_setting_candidates_expires_at",
        table_name="system_setting_candidates",
    )
    op.drop_index(
        "ix_system_setting_candidates_created_by_user_id",
        table_name="system_setting_candidates",
    )
    op.drop_table("system_setting_candidates")
    op.drop_index(
        "ix_system_settings_updated_by_user_id",
        table_name="system_settings",
    )
    op.drop_table("system_settings")

    bind = op.get_bind()
    system_data_migration_outcome.drop(bind, checkfirst=True)
    system_setting_audit_source.drop(bind, checkfirst=True)
    system_setting_audit_event_type.drop(bind, checkfirst=True)
    system_setting_health_status.drop(bind, checkfirst=True)
    system_setting_validation_status.drop(bind, checkfirst=True)
    system_setting_section.drop(bind, checkfirst=True)
