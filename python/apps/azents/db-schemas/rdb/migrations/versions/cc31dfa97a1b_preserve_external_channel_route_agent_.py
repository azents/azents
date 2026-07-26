"""Preserve External Channel route Agent history."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "cc31dfa97a1b"
down_revision: str | Sequence[str] | None = "00ae8d1fd42c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Separate the active Agent association from immutable route provenance."""
    op.add_column(
        "external_channel_agent_routes",
        sa.Column("agent_id_snapshot", sa.String(length=32), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE external_channel_agent_routes "
            "SET agent_id_snapshot = agent_id "
            "WHERE agent_id_snapshot IS NULL"
        )
    )
    op.execute(
        """
        CREATE FUNCTION preserve_external_channel_route_agent_snapshot()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.agent_id_snapshot IS NULL THEN
                    NEW.agent_id_snapshot := NEW.agent_id;
                END IF;
                IF NEW.agent_id_snapshot IS NULL
                   OR NEW.agent_id_snapshot IS DISTINCT FROM NEW.agent_id THEN
                    RAISE EXCEPTION
                        'External Channel route Agent snapshot must match Agent';
                END IF;
            ELSIF NEW.agent_id_snapshot
                    IS DISTINCT FROM OLD.agent_id_snapshot THEN
                RAISE EXCEPTION
                    'External Channel route Agent snapshot is immutable';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER external_channel_agent_routes_agent_snapshot_immutable
        BEFORE INSERT OR UPDATE OF agent_id_snapshot
        ON external_channel_agent_routes
        FOR EACH ROW
        EXECUTE FUNCTION preserve_external_channel_route_agent_snapshot()
        """
    )
    op.alter_column(
        "external_channel_agent_routes",
        "agent_id_snapshot",
        nullable=False,
    )
    op.drop_constraint(
        "uq_external_channel_agent_routes_connection_agent",
        "external_channel_agent_routes",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_external_channel_agent_routes_connection_agent",
        "external_channel_agent_routes",
        ["connection_id", "agent_id_snapshot"],
    )
    op.drop_constraint(
        "external_channel_agent_routes_agent_id_fkey",
        "external_channel_agent_routes",
        type_="foreignkey",
    )
    op.alter_column(
        "external_channel_agent_routes",
        "agent_id",
        nullable=True,
    )
    op.create_foreign_key(
        "external_channel_agent_routes_agent_id_fkey",
        "external_channel_agent_routes",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_external_channel_agent_routes_available_agent",
        "external_channel_agent_routes",
        "catalog_status = 'removed' OR agent_id IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_external_channel_agent_routes_agent_snapshot",
        "external_channel_agent_routes",
        "agent_id IS NULL OR agent_id = agent_id_snapshot",
    )


def downgrade() -> None:
    """Restore the mandatory active Agent association when no route detached it."""
    route_id = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT id FROM external_channel_agent_routes "
                "WHERE agent_id IS NULL ORDER BY id LIMIT 1"
            )
        )
        .scalar_one_or_none()
    )
    if route_id is not None:
        raise RuntimeError(
            "Cannot remove External Channel route Agent history: "
            f"detached route exists: {route_id}."
        )
    op.drop_constraint(
        "ck_external_channel_agent_routes_agent_snapshot",
        "external_channel_agent_routes",
        type_="check",
    )
    op.drop_constraint(
        "ck_external_channel_agent_routes_available_agent",
        "external_channel_agent_routes",
        type_="check",
    )
    op.drop_constraint(
        "external_channel_agent_routes_agent_id_fkey",
        "external_channel_agent_routes",
        type_="foreignkey",
    )
    op.alter_column(
        "external_channel_agent_routes",
        "agent_id",
        nullable=False,
    )
    op.create_foreign_key(
        "external_channel_agent_routes_agent_id_fkey",
        "external_channel_agent_routes",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_external_channel_agent_routes_connection_agent",
        "external_channel_agent_routes",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_external_channel_agent_routes_connection_agent",
        "external_channel_agent_routes",
        ["connection_id", "agent_id"],
    )
    op.execute(
        """
        DROP TRIGGER external_channel_agent_routes_agent_snapshot_immutable
        ON external_channel_agent_routes
        """
    )
    op.execute("DROP FUNCTION preserve_external_channel_route_agent_snapshot()")
    op.drop_column("external_channel_agent_routes", "agent_id_snapshot")
