"""Globalize external account links and preserve legacy provenance.

Revision ID: e905bfe74372
Revises: 7e77cf7a8877
Create Date: 2026-09-13

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e905bfe74372"
down_revision: str | Sequence[str] | None = "7e77cf7a8877"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Convert active link ownership from Workspace-scoped to global."""
    postgresql.ENUM(
        "owner_disconnected",
        "legacy_redundant",
        "legacy_conflict",
        name="external_account_link_revocation_reason",
    ).create(op.get_bind(), checkfirst=True)
    op.add_column(
        "external_account_links",
        sa.Column(
            "revocation_reason",
            postgresql.ENUM(
                name="external_account_link_revocation_reason",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.drop_index(
        "uq_external_account_links_active_user_provider_scope",
        table_name="external_account_links",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_index(
        "uq_external_account_links_active_external_identity",
        table_name="external_account_links",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_index(
        "ix_external_account_links_workspace_id",
        table_name="external_account_links",
    )
    op.alter_column(
        "external_account_links",
        "provider_tenant_display_label",
        existing_type=sa.String(length=255),
        nullable=True,
    )
    op.alter_column(
        "external_account_links",
        "workspace_id",
        new_column_name="legacy_workspace_id",
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )
    op.alter_column(
        "external_account_links",
        "legacy_workspace_id",
        existing_type=sa.String(length=32),
        nullable=True,
    )
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE constraint_name text;
            BEGIN
                SELECT tc.constraint_name
                INTO constraint_name
                FROM information_schema.table_constraints AS tc
                WHERE tc.table_schema = current_schema()
                  AND tc.table_name = 'external_account_links'
                  AND tc.constraint_type = 'FOREIGN KEY'
                  AND tc.constraint_name LIKE 'external_account_links%workspace%';
                IF constraint_name IS NOT NULL THEN
                    EXECUTE format(
                        'ALTER TABLE external_account_links DROP CONSTRAINT %I',
                        constraint_name
                    );
                END IF;
            END $$;
            """
        )
    )
    op.create_foreign_key(
        "fk_external_account_links_legacy_workspace_id",
        "external_account_links",
        "workspaces",
        ["legacy_workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        sa.text(
            """
            WITH owners AS (
                SELECT
                    provider,
                    identity_scope,
                    provider_user_id,
                    count(DISTINCT user_id) AS owner_count
                FROM external_account_links
                WHERE revoked_at IS NULL
                GROUP BY provider, identity_scope, provider_user_id
            ),
            ranked AS (
                SELECT
                    id,
                    provider,
                    identity_scope,
                    provider_user_id,
                    user_id,
                    row_number() OVER (
                        PARTITION BY
                            provider,
                            identity_scope,
                            provider_user_id,
                            user_id
                        ORDER BY linked_at, id
                    ) AS user_rank
                FROM external_account_links
                WHERE revoked_at IS NULL
            )
            UPDATE external_account_links AS link
            SET
                revoked_at = now(),
                revocation_reason = CASE
                    WHEN owners.owner_count > 1
                        THEN 'legacy_conflict'::external_account_link_revocation_reason
                    ELSE 'legacy_redundant'::external_account_link_revocation_reason
                END
            FROM ranked
            JOIN owners
              ON owners.provider = ranked.provider
             AND owners.identity_scope = ranked.identity_scope
             AND owners.provider_user_id = ranked.provider_user_id
            WHERE link.id = ranked.id
              AND (
                  owners.owner_count > 1
                  OR ranked.user_rank > 1
              )
            """
        )
    )
    op.create_index(
        "uq_external_account_links_active_external_identity",
        "external_account_links",
        ["provider", "identity_scope", "provider_user_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_external_account_links_legacy_workspace_id",
        "external_account_links",
        ["legacy_workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    """Restore the prior physical column and Workspace-scoped indexes."""
    op.drop_index(
        "ix_external_account_links_legacy_workspace_id",
        table_name="external_account_links",
    )
    op.drop_index(
        "uq_external_account_links_active_external_identity",
        table_name="external_account_links",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_constraint(
        "fk_external_account_links_legacy_workspace_id",
        "external_account_links",
        type_="foreignkey",
    )
    op.alter_column(
        "external_account_links",
        "legacy_workspace_id",
        new_column_name="workspace_id",
        existing_type=sa.String(length=32),
        existing_nullable=True,
    )
    op.create_foreign_key(
        "fk_external_account_links_workspace_id",
        "external_account_links",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("external_account_links", "revocation_reason")
    postgresql.ENUM(
        name="external_account_link_revocation_reason",
    ).drop(op.get_bind(), checkfirst=True)
    op.create_index(
        "ix_external_account_links_workspace_id",
        "external_account_links",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "uq_external_account_links_active_external_identity",
        "external_account_links",
        ["workspace_id", "provider", "identity_scope", "provider_user_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "uq_external_account_links_active_user_provider_scope",
        "external_account_links",
        ["workspace_id", "user_id", "provider", "identity_scope"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
