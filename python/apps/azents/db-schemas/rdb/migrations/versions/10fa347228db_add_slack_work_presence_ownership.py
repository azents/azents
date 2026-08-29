"""add Slack work presence ownership

Revision ID: 10fa347228db
Revises: 2c2b5240fe20
Create Date: 2026-08-29 10:42:42.268128

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "10fa347228db"
down_revision: str | Sequence[str] | None = "2c2b5240fe20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add Slack presence ownership and advance Channel Work state."""
    op.add_column(
        "external_channel_connections",
        sa.Column("slack_presence_lease_owner", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "external_channel_connections",
        sa.Column(
            "slack_presence_lease_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "external_channel_connections",
        sa.Column(
            "slack_presence_heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_external_channel_connections_slack_presence_lease_until",
        "external_channel_connections",
        ["slack_presence_lease_until"],
        unique=False,
    )
    _require_channel_work_schema(2, fields_present=False)
    op.execute(
        sa.text(
            """
            UPDATE toolkit_states
            SET
                state_json = state_json || jsonb_build_object(
                    'schema_version', 3,
                    'slack_presence_thread_ts', NULL,
                    'slack_presence_initiator_user_id', NULL
                ),
                schema_version = 3,
                version = version + 1,
                updated_at = now()
            WHERE toolkit_namespace = 'external_channel'
              AND state_name LIKE 'channel_work:%'
              AND schema_version = 2
            """
        )
    )


def downgrade() -> None:
    """Remove Slack presence ownership and restore Work schema version 2."""
    _require_channel_work_schema(3, fields_present=True)
    op.execute(
        sa.text(
            """
            UPDATE toolkit_states
            SET
                state_json = (
                    state_json
                    - 'slack_presence_thread_ts'
                    - 'slack_presence_initiator_user_id'
                ) || jsonb_build_object('schema_version', 2),
                schema_version = 2,
                version = version + 1,
                updated_at = now()
            WHERE toolkit_namespace = 'external_channel'
              AND state_name LIKE 'channel_work:%'
              AND schema_version = 3
            """
        )
    )
    op.drop_index(
        "ix_external_channel_connections_slack_presence_lease_until",
        table_name="external_channel_connections",
    )
    op.drop_column(
        "external_channel_connections",
        "slack_presence_heartbeat_at",
    )
    op.drop_column(
        "external_channel_connections",
        "slack_presence_lease_until",
    )
    op.drop_column(
        "external_channel_connections",
        "slack_presence_lease_owner",
    )


def _require_channel_work_schema(
    schema_version: int,
    *,
    fields_present: bool,
) -> None:
    """Require one exact migration source shape before rewriting Work state."""
    field_clause = (
        "state_json ? 'slack_presence_thread_ts' "
        "AND state_json ? 'slack_presence_initiator_user_id'"
        if fields_present
        else "NOT state_json ? 'slack_presence_thread_ts' "
        "AND NOT state_json ? 'slack_presence_initiator_user_id'"
    )
    invalid = op.get_bind().scalar(
        sa.text(
            f"""
            SELECT count(*)
            FROM toolkit_states
            WHERE toolkit_namespace = 'external_channel'
              AND state_name LIKE 'channel_work:%'
              AND NOT (
                  schema_version = :schema_version
                  AND state_json->>'schema_version' = :schema_version_text
                  AND {field_clause}
              )
            """
        ),
        {
            "schema_version": schema_version,
            "schema_version_text": str(schema_version),
        },
    )
    if invalid:
        raise RuntimeError("Channel Work Toolkit State schema is inconsistent")
