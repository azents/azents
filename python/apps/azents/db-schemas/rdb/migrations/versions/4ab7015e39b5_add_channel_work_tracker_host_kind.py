"""Add Channel Work Tracker host kind.

Revision ID: 4ab7015e39b5
Revises: 7de5749cadd5
Create Date: 2026-09-05 18:02:45.124066

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4ab7015e39b5"
down_revision: str | Sequence[str] | None = "7de5749cadd5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Classify every existing Channel Work Tracker host as standalone."""
    _require_channel_work_schema(
        schema_version=4,
        host_kind_present=False,
        require_standalone=False,
    )
    op.execute(
        sa.text(
            """
            UPDATE toolkit_states
            SET
                state_json = state_json || jsonb_build_object(
                    'schema_version', 5,
                    'projection_parts', (
                        SELECT coalesce(
                            jsonb_agg(
                                part || jsonb_build_object(
                                    'host_kind', 'standalone'
                                )
                                ORDER BY ordinal
                            ),
                            '[]'::jsonb
                        )
                        FROM jsonb_array_elements(
                            state_json->'projection_parts'
                        ) WITH ORDINALITY AS projection(part, ordinal)
                    )
                ),
                schema_version = 5,
                version = version + 1,
                updated_at = now()
            WHERE toolkit_namespace = 'external_channel'
              AND state_name LIKE 'channel_work:%'
              AND schema_version = 4
            """
        )
    )


def downgrade() -> None:
    """Restore schema version 4 when every Tracker host is standalone."""
    _require_channel_work_schema(
        schema_version=5,
        host_kind_present=True,
        require_standalone=True,
    )
    op.execute(
        sa.text(
            """
            UPDATE toolkit_states
            SET
                state_json = state_json || jsonb_build_object(
                    'schema_version', 4,
                    'projection_parts', (
                        SELECT coalesce(
                            jsonb_agg(
                                part - 'host_kind'
                                ORDER BY ordinal
                            ),
                            '[]'::jsonb
                        )
                        FROM jsonb_array_elements(
                            state_json->'projection_parts'
                        ) WITH ORDINALITY AS projection(part, ordinal)
                    )
                ),
                schema_version = 4,
                version = version + 1,
                updated_at = now()
            WHERE toolkit_namespace = 'external_channel'
              AND state_name LIKE 'channel_work:%'
              AND schema_version = 5
            """
        )
    )


def _require_channel_work_schema(
    *,
    schema_version: int,
    host_kind_present: bool,
    require_standalone: bool,
) -> None:
    """Require one exact migration source shape before rewriting Work state."""
    host_clause = (
        "part ? 'host_kind'" if host_kind_present else "NOT part ? 'host_kind'"
    )
    standalone_clause = (
        "AND part->>'host_kind' = 'standalone'" if require_standalone else ""
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
                  AND jsonb_typeof(state_json->'projection_parts') = 'array'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM jsonb_array_elements(
                          state_json->'projection_parts'
                      ) AS projection(part)
                      WHERE jsonb_typeof(part) != 'object'
                         OR NOT ({host_clause} {standalone_clause})
                  )
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
