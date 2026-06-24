"""user system

Revision ID: 74fb22803d00
Revises: d1fe85d604de
Create Date: 2026-02-19 06:37:33.803821

"""

# pyright: reportUnknownArgumentType=false

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "74fb22803d00"
down_revision: str | Sequence[str] | None = "d1fe85d604de"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Migrate to the user system."""
    # 1. Create the users table, recreating it because a previous migration dropped it
    op.create_table(
        "users",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("primary_email_id", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 2. Create the user_emails table
    op.create_table(
        "user_emails",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("email", name="uq_user_emails_email"),
    )

    # 3. Create the email_verifications table
    op.create_table(
        "email_verifications",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("code", sa.String(6), nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 4. Add user_id to workspace_users, nullable first
    op.add_column(
        "workspace_users",
        sa.Column("user_id", sa.String(32), nullable=True),
    )

    # 5. Add user_id to sessions, nullable first
    op.add_column(
        "sessions",
        sa.Column("user_id", sa.String(32), nullable=True),
    )

    # 6. Data migration in PL/pgSQL:
    #    For each unique email in workspace_user_identities,
    #    create a user and user_email,
    #    and map user_id onto workspace_users and sessions
    op.execute(
        sa.text("""
        DO $$
        DECLARE
            rec RECORD;
            new_user_id TEXT;
            new_email_id TEXT;
        BEGIN
            FOR rec IN
                SELECT DISTINCT ON (email) email, created_at
                FROM workspace_user_identities
                ORDER BY email, created_at ASC
            LOOP
                new_user_id := replace(
                    gen_random_uuid()::text, '-', ''
                );
                new_email_id := replace(
                    gen_random_uuid()::text, '-', ''
                );

                -- Create User
                INSERT INTO users (id, created_at, updated_at)
                VALUES (new_user_id, rec.created_at, now());

                -- Create UserEmail
                INSERT INTO user_emails (
                    id, user_id, email,
                    verified_at, created_at, updated_at
                )
                VALUES (
                    new_email_id, new_user_id, rec.email,
                    now(), now(), now()
                );

                -- Update primary_email_id
                UPDATE users
                SET primary_email_id = new_email_id
                WHERE id = new_user_id;
            END LOOP;
        END $$;

        -- Map workspace_users.user_id
        UPDATE workspace_users wu
        SET user_id = ue.user_id
        FROM workspace_user_identities wui
        JOIN user_emails ue ON ue.email = wui.email
        WHERE wui.workspace_user_id = wu.id;

        -- Map sessions.user_id
        UPDATE sessions s
        SET user_id = ue.user_id
        FROM workspace_user_identities wui
        JOIN user_emails ue ON ue.email = wui.email
        WHERE wui.id = s.workspace_user_identity_id;
        """)
    )

    # 7. Apply NOT NULL constraints
    op.alter_column("workspace_users", "user_id", nullable=False)
    op.alter_column("sessions", "user_id", nullable=False)
    op.alter_column("users", "primary_email_id", nullable=False)

    # 8. Add FKs, marked DEFERRABLE because they are cyclic
    op.execute(
        """
        ALTER TABLE users
        ADD CONSTRAINT fk_users_primary_email_id
        FOREIGN KEY (primary_email_id)
        REFERENCES user_emails (id)
        DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.create_foreign_key(
        "fk_workspace_users_user_id",
        "workspace_users",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_sessions_user_id",
        "sessions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 9. Add unique constraints
    op.create_unique_constraint(
        "uq_workspace_users_workspace_user",
        "workspace_users",
        ["workspace_id", "user_id"],
    )

    # 10. Drop existing FK and index from sessions
    op.drop_index("ix_sessions_workspace_user_identity_id", table_name="sessions")
    op.drop_constraint(
        "sessions_workspace_user_identity_id_fkey",
        "sessions",
        type_="foreignkey",
    )
    op.drop_column("sessions", "workspace_user_identity_id")

    # 11. Drop existing authentication-related tables
    op.drop_table("password_logins")
    op.drop_table("login_email_verifications")
    op.drop_table("workspace_creation_email_verifications")
    op.drop_table("workspace_user_identities")

    # 12. Create sessions.user_id index
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])


def downgrade() -> None:
    """Roll back the user system migration.

    Warning: this does not include data migration rollback.
    It only restores the schema to its original state.
    """
    # Drop sessions.user_id index
    op.drop_index("ix_sessions_user_id", table_name="sessions")

    # Restore existing authentication-related tables
    op.create_table(
        "workspace_user_identities",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_user_id",
            sa.String(32),
            sa.ForeignKey("workspace_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "email",
            name="uq_workspace_user_identities_workspace_email",
        ),
        sa.UniqueConstraint(
            "workspace_user_id",
            name="uq_workspace_user_identities_workspace_user",
        ),
    )

    op.create_table(
        "password_logins",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_user_identity_id",
            sa.String(32),
            sa.ForeignKey("workspace_user_identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "workspace_user_identity_id",
            name="uq_password_logins_identity",
        ),
    )

    op.create_table(
        "login_email_verifications",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("code", sa.String(6), nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "workspace_creation_email_verifications",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("code", sa.String(6), nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Restore workspace_user_identity_id to sessions
    op.add_column(
        "sessions",
        sa.Column("workspace_user_identity_id", sa.String(32), nullable=True),
    )
    op.create_foreign_key(
        "sessions_workspace_user_identity_id_fkey",
        "sessions",
        "workspace_user_identities",
        ["workspace_user_identity_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_sessions_workspace_user_identity_id",
        "sessions",
        ["workspace_user_identity_id"],
    )

    # Drop unique constraints
    op.drop_constraint(
        "uq_workspace_users_workspace_user", "workspace_users", type_="unique"
    )

    # Drop FKs
    op.drop_constraint("fk_sessions_user_id", "sessions", type_="foreignkey")
    op.drop_constraint(
        "fk_workspace_users_user_id", "workspace_users", type_="foreignkey"
    )
    op.drop_constraint("fk_users_primary_email_id", "users", type_="foreignkey")

    # Drop user_id columns
    op.drop_column("sessions", "user_id")
    op.drop_column("workspace_users", "user_id")

    # Drop new tables
    op.drop_table("email_verifications")
    op.drop_table("user_emails")
    op.drop_table("users")
