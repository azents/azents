"""Remove External Channel Session activation.

Revision ID: c67332e97043
Revises: b64a4e25ab8b
Create Date: 2026-08-01 01:03:47.897004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c67332e97043"
down_revision: str | Sequence[str] | None = "b64a4e25ab8b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVATION_STATE = postgresql.ENUM(
    "initializing",
    "activated",
    "blocked",
    name="external_channel_session_activation_state",
    create_type=False,
)


def upgrade() -> None:
    """Fold retained inputs into cursor authority and remove activation state."""
    op.execute(
        sa.text(
            """
            UPDATE external_channel_conversation_positions AS position
            SET read_through_position = retained.trigger_position
            FROM (
                SELECT
                    activation.conversation_position_id,
                    MAX(activation.trigger_position) AS trigger_position
                FROM external_channel_session_activations AS activation
                JOIN mailbox_items AS mailbox
                  ON mailbox.id = activation.mailbox_item_id
                GROUP BY activation.conversation_position_id
            ) AS retained
            WHERE position.id = retained.conversation_position_id
              AND (
                  position.read_through_position IS NULL
                  OR position.read_through_position < retained.trigger_position
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE agent_sessions AS session
            SET run_state = 'running', run_heartbeat_at = NOW()
            FROM (
                SELECT DISTINCT activation.agent_session_id
                FROM external_channel_session_activations AS activation
                JOIN mailbox_items AS mailbox
                  ON mailbox.id = activation.mailbox_item_id
            ) AS retained
            WHERE session.id = retained.agent_session_id
              AND session.status = 'active'
              AND session.run_state <> 'running'
            """
        )
    )
    op.drop_table("external_channel_session_activation_deliveries")
    op.drop_table("external_channel_session_activations")
    op.drop_constraint(
        "uq_external_channel_bindings_id_agent_session",
        "external_channel_bindings",
        type_="unique",
    )
    _ACTIVATION_STATE.drop(op.get_bind())


def downgrade() -> None:
    """Restore the removed activation schema without reconstructing prior rows."""
    _ACTIVATION_STATE.create(op.get_bind())
    op.create_unique_constraint(
        "uq_external_channel_bindings_id_agent_session",
        "external_channel_bindings",
        ["id", "agent_session_id"],
    )
    op.create_table(
        "external_channel_session_activations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("connection_id", sa.String(length=32), nullable=False),
        sa.Column("conversation_position_id", sa.String(length=32), nullable=False),
        sa.Column("binding_id", sa.String(length=32), nullable=False),
        sa.Column("agent_session_id", sa.String(length=32), nullable=False),
        sa.Column("trigger_provider_message_key", sa.Text(), nullable=False),
        sa.Column("trigger_position", sa.Text(), nullable=False),
        sa.Column("range_start_position", sa.Text(), nullable=True),
        sa.Column(
            "state",
            _ACTIVATION_STATE,
            server_default="initializing",
            nullable=False,
        ),
        sa.Column("mailbox_item_id", sa.String(length=32), nullable=False),
        sa.Column("failure_kind", sa.String(length=120), nullable=True),
        sa.Column("failure_summary", sa.String(length=255), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "mailbox_item_id IS NOT NULL AND "
            "((state = 'initializing' "
            "AND failure_kind IS NULL AND failure_summary IS NULL "
            "AND activated_at IS NULL AND blocked_at IS NULL) "
            "OR (state = 'activated' "
            "AND failure_kind IS NULL AND failure_summary IS NULL "
            "AND activated_at IS NOT NULL AND blocked_at IS NULL) "
            "OR (state = 'blocked' "
            "AND failure_kind IS NOT NULL AND failure_summary IS NOT NULL "
            "AND activated_at IS NULL AND blocked_at IS NOT NULL))",
            name="ck_external_channel_session_activations_state_fields",
        ),
        sa.ForeignKeyConstraint(
            ["agent_session_id"],
            ["agent_sessions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["external_channel_bindings.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id", "agent_session_id"],
            [
                "external_channel_bindings.id",
                "external_channel_bindings.agent_session_id",
            ],
            name="fk_external_channel_session_activations_binding_session",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "conversation_position_id"],
            [
                "external_channel_conversation_positions.connection_id",
                "external_channel_conversation_positions.id",
            ],
            name="fk_external_channel_session_activations_connection_position",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mailbox_item_id",
            name="uq_external_channel_session_activations_mailbox_item",
        ),
        sa.UniqueConstraint(
            "conversation_position_id",
            "trigger_provider_message_key",
            "trigger_position",
            name="uq_external_channel_session_activations_position_trigger",
        ),
    )
    op.create_index(
        "ix_external_channel_session_activations_agent_session_id",
        "external_channel_session_activations",
        ["agent_session_id"],
    )
    op.create_index(
        "ix_external_channel_session_activations_binding_id",
        "external_channel_session_activations",
        ["binding_id"],
    )
    op.create_index(
        "uq_external_channel_session_activations_position_barrier",
        "external_channel_session_activations",
        ["conversation_position_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('initializing', 'blocked')"),
    )
    op.create_table(
        "external_channel_session_activation_deliveries",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("activation_id", sa.String(length=32), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("delivery_attempt_id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["activation_id"],
            ["external_channel_session_activations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["delivery_attempt_id"],
            ["external_channel_delivery_attempts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "activation_id",
            "delivery_attempt_id",
            name="uq_external_channel_session_activation_deliveries_attempt",
        ),
        sa.UniqueConstraint(
            "activation_id",
            "ordinal",
            name="uq_external_channel_session_activation_deliveries_ordinal",
        ),
    )
