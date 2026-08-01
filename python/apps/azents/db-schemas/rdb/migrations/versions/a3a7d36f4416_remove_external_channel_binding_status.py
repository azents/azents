"""Remove External Channel binding status."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a3a7d36f4416"
down_revision: str | Sequence[str] | None = "aafb89c5904b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BINDING_STATUS = postgresql.ENUM(
    "active",
    "disconnected",
    name="external_channel_binding_status",
    create_type=False,
)


def upgrade() -> None:
    """Use the terminal timestamp as the only binding connectedness authority."""
    inconsistent_binding_count = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT count(*)
            FROM external_channel_bindings
            WHERE (status = 'active' AND disconnected_at IS NOT NULL)
               OR (status = 'disconnected' AND disconnected_at IS NULL)
            """
            )
        )
        .scalar_one()
    )
    if inconsistent_binding_count:
        raise RuntimeError("External Channel binding lifecycle data is inconsistent.")

    op.drop_index(
        "uq_external_channel_bindings_active_resource",
        table_name="external_channel_bindings",
    )
    op.drop_index(
        "ix_external_channel_bindings_route_id_status",
        table_name="external_channel_bindings",
    )
    op.drop_index(
        "ix_external_channel_bindings_agent_session_id_status",
        table_name="external_channel_bindings",
    )
    op.create_index(
        "ix_external_channel_bindings_agent_session_id",
        "external_channel_bindings",
        ["agent_session_id"],
    )
    op.create_index(
        "ix_external_channel_bindings_route_id",
        "external_channel_bindings",
        ["route_id"],
    )
    op.create_index(
        "uq_external_channel_bindings_connected_resource",
        "external_channel_bindings",
        ["resource_id"],
        unique=True,
        postgresql_where=sa.text("disconnected_at IS NULL"),
    )
    op.drop_column("external_channel_bindings", "status")
    _BINDING_STATUS.drop(op.get_bind())


def downgrade() -> None:
    """Restore the redundant status projection from the terminal timestamp."""
    _BINDING_STATUS.create(op.get_bind())
    op.add_column(
        "external_channel_bindings",
        sa.Column(
            "status",
            _BINDING_STATUS,
            server_default="active",
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE external_channel_bindings
            SET status = CASE
                WHEN disconnected_at IS NULL
                THEN 'active'::external_channel_binding_status
                ELSE 'disconnected'::external_channel_binding_status
            END
            """
        )
    )
    op.alter_column(
        "external_channel_bindings",
        "status",
        existing_type=_BINDING_STATUS,
        nullable=False,
        existing_server_default="active",
    )

    op.drop_index(
        "uq_external_channel_bindings_connected_resource",
        table_name="external_channel_bindings",
    )
    op.drop_index(
        "ix_external_channel_bindings_route_id",
        table_name="external_channel_bindings",
    )
    op.drop_index(
        "ix_external_channel_bindings_agent_session_id",
        table_name="external_channel_bindings",
    )
    op.create_index(
        "ix_external_channel_bindings_agent_session_id_status",
        "external_channel_bindings",
        ["agent_session_id", "status"],
    )
    op.create_index(
        "ix_external_channel_bindings_route_id_status",
        "external_channel_bindings",
        ["route_id", "status"],
    )
    op.create_index(
        "uq_external_channel_bindings_active_resource",
        "external_channel_bindings",
        ["resource_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
