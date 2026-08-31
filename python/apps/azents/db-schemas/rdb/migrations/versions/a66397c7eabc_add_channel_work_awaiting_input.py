"""Add Channel Work awaiting input state.

Revision ID: a66397c7eabc
Revises: 629612c66084
Create Date: 2026-08-31 15:41:51.645912

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a66397c7eabc"
down_revision: str | Sequence[str] | None = "629612c66084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Advance Channel Work state to schema version 4."""
    _require_channel_work_schema(
        3,
        awaiting_field_present=False,
        require_awaiting_null=False,
    )
    op.execute(
        sa.text(
            """
            UPDATE toolkit_states
            SET
                state_json = state_json || jsonb_build_object(
                    'schema_version', 4,
                    'awaiting_input_run_id', NULL
                ),
                schema_version = 4,
                version = version + 1,
                updated_at = now()
            WHERE toolkit_namespace = 'external_channel'
              AND state_name LIKE 'channel_work:%'
              AND schema_version = 3
            """
        )
    )


def downgrade() -> None:
    """Restore Channel Work state schema version 3 after awaiting is cleared."""
    _require_channel_work_schema(
        4,
        awaiting_field_present=True,
        require_awaiting_null=True,
    )
    op.execute(
        sa.text(
            """
            UPDATE toolkit_states
            SET
                state_json = (
                    state_json - 'awaiting_input_run_id'
                ) || jsonb_build_object('schema_version', 3),
                schema_version = 3,
                version = version + 1,
                updated_at = now()
            WHERE toolkit_namespace = 'external_channel'
              AND state_name LIKE 'channel_work:%'
              AND schema_version = 4
            """
        )
    )


def _require_channel_work_schema(
    schema_version: int,
    *,
    awaiting_field_present: bool,
    require_awaiting_null: bool,
) -> None:
    """Require one exact migration source shape before rewriting Work state."""
    field_clause = (
        "state_json ? 'awaiting_input_run_id'"
        if awaiting_field_present
        else "NOT state_json ? 'awaiting_input_run_id'"
    )
    null_clause = (
        "AND state_json->'awaiting_input_run_id' = 'null'::jsonb"
        if require_awaiting_null
        else ""
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
                  {null_clause}
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
