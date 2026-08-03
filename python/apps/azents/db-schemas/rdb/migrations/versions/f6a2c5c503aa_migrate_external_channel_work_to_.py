"""Migrate External Channel Work to Toolkit State."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f6a2c5c503aa"
down_revision: str | Sequence[str] | None = "ef9fddb71222"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WORK_STATUS_VALUES = ("active", "finished")
_PROJECTION_STATUS_VALUES = ("present", "failed", "unknown", "deleted")
_TOOLKIT_NAMESPACE = "external_channel"
_STATE_NAME_PREFIX = "channel_work:"


def upgrade() -> None:
    """Backfill current Work state and remove the dedicated storage authority."""
    op.execute(
        sa.text(
            """
            LOCK TABLE external_channel_works,
                       external_channel_work_projection_parts
            IN ACCESS EXCLUSIVE MODE
            """
        )
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    WITH ranked_work AS (
                        SELECT
                            work.binding_id,
                            row_number() OVER (
                                PARTITION BY work.binding_id
                                ORDER BY
                                    (work.status::text = 'active') DESC,
                                    work.created_at DESC,
                                    work.id DESC
                            ) AS rank
                        FROM external_channel_works AS work
                    )
                    SELECT 1
                    FROM ranked_work AS selected
                    JOIN external_channel_bindings AS binding
                      ON binding.id = selected.binding_id
                    JOIN agent_sessions AS agent_session
                      ON agent_session.id = binding.agent_session_id
                    JOIN toolkit_states AS state
                      ON state.agent_id = agent_session.agent_id
                     AND state.session_id = agent_session.id
                     AND state.toolkit_namespace = 'external_channel'
                     AND state.state_name =
                         'channel_work:' || selected.binding_id
                    WHERE selected.rank = 1
                ) THEN
                    RAISE EXCEPTION
                        'External Channel Work Toolkit State identity already exists';
                END IF;
            END
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH ranked_work AS (
                SELECT
                    work.*,
                    row_number() OVER (
                        PARTITION BY work.binding_id
                        ORDER BY
                            (work.status::text = 'active') DESC,
                            work.created_at DESC,
                            work.id DESC
                    ) AS rank
                FROM external_channel_works AS work
            ),
            selected_work AS (
                SELECT *
                FROM ranked_work
                WHERE rank = 1
            )
            INSERT INTO toolkit_states (
                id,
                agent_id,
                session_id,
                toolkit_namespace,
                state_name,
                state_json,
                schema_version,
                version
            )
            SELECT
                md5('channel-260803:' || work.id),
                agent_session.agent_id,
                agent_session.id,
                'external_channel',
                'channel_work:' || work.binding_id,
                jsonb_build_object(
                    'schema_version', 1,
                    'binding_id', work.binding_id,
                    'work_cycle_id', work.id,
                    'status', work.status::text,
                    'title', work.title,
                    'tasks', work.tasks,
                    'state_revision', work.state_revision,
                    'desired_progress_revision',
                        work.desired_progress_revision,
                    'desired_progress', work.desired_progress_payload,
                    'finished_at', work.finished_at,
                    'projection_parts', COALESCE(
                        (
                            SELECT jsonb_agg(
                                jsonb_build_object(
                                    'part_ordinal', part.part_ordinal,
                                    'desired_progress_revision',
                                        part.desired_progress_revision,
                                    'status', part.status::text,
                                    'provider_message_key',
                                        part.provider_message_key
                                )
                                ORDER BY part.part_ordinal
                            )
                            FROM external_channel_work_projection_parts AS part
                            WHERE part.work_id = work.id
                        ),
                        '[]'::jsonb
                    )
                ),
                1,
                1
            FROM selected_work AS work
            JOIN external_channel_bindings AS binding
              ON binding.id = work.binding_id
            JOIN agent_sessions AS agent_session
              ON agent_session.id = binding.agent_session_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE
                selected_count bigint;
                migrated_count bigint;
            BEGIN
                SELECT count(*)
                INTO selected_count
                FROM (
                    SELECT DISTINCT ON (work.binding_id)
                        work.binding_id
                    FROM external_channel_works AS work
                    ORDER BY
                        work.binding_id,
                        (work.status::text = 'active') DESC,
                        work.created_at DESC,
                        work.id DESC
                ) AS selected;

                SELECT count(*)
                INTO migrated_count
                FROM (
                    SELECT
                        work.*,
                        row_number() OVER (
                            PARTITION BY work.binding_id
                            ORDER BY
                                (work.status::text = 'active') DESC,
                                work.created_at DESC,
                                work.id DESC
                        ) AS rank
                    FROM external_channel_works AS work
                ) AS selected
                JOIN external_channel_bindings AS binding
                  ON binding.id = selected.binding_id
                JOIN agent_sessions AS agent_session
                  ON agent_session.id = binding.agent_session_id
                JOIN toolkit_states AS state
                  ON state.id = md5('channel-260803:' || selected.id)
                 AND state.agent_id = agent_session.agent_id
                 AND state.session_id = agent_session.id
                 AND state.toolkit_namespace = 'external_channel'
                 AND state.state_name =
                     'channel_work:' || selected.binding_id
                 AND state.state_json ->> 'work_cycle_id' = selected.id
                WHERE selected.rank = 1;

                IF selected_count <> migrated_count THEN
                    RAISE EXCEPTION
                        'External Channel Work migration count mismatch: % <> %',
                        selected_count,
                        migrated_count;
                END IF;
            END
            $$;
            """
        )
    )
    op.drop_table("external_channel_work_projection_parts")
    op.drop_table("external_channel_works")
    op.execute(sa.text("DROP TYPE external_channel_work_status"))


def downgrade() -> None:
    """Reconstruct the retained current or latest Work representation."""
    quoted_work_statuses = ", ".join(f"'{value}'" for value in _WORK_STATUS_VALUES)
    op.execute(
        sa.text(
            f"CREATE TYPE external_channel_work_status AS ENUM ({quoted_work_statuses})"
        )
    )
    work_status_enum = postgresql.ENUM(
        *_WORK_STATUS_VALUES,
        name="external_channel_work_status",
        create_type=False,
    )
    projection_status_enum = postgresql.ENUM(
        *_PROJECTION_STATUS_VALUES,
        name="external_channel_work_projection_status",
        create_type=False,
    )
    op.create_table(
        "external_channel_works",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("binding_id", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            work_status_enum,
            server_default="active",
            nullable=False,
        ),
        sa.Column("schema_version", sa.Integer(), server_default="2", nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("tasks", postgresql.JSONB(), nullable=False),
        sa.Column(
            "state_revision",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "desired_progress_revision",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "desired_progress_payload",
            postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["external_channel_bindings.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_channel_works_binding_id_status",
        "external_channel_works",
        ["binding_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_external_channel_works_active_binding",
        "external_channel_works",
        ["binding_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "external_channel_work_projection_parts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("work_id", sa.String(length=32), nullable=False),
        sa.Column("part_ordinal", sa.Integer(), nullable=False),
        sa.Column(
            "desired_progress_revision",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column("status", projection_status_enum, nullable=False),
        sa.Column(
            "provider_message_key",
            sa.String(length=255),
            nullable=True,
        ),
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
        sa.ForeignKeyConstraint(
            ["work_id"],
            ["external_channel_works.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "work_id",
            "part_ordinal",
            name="uq_external_channel_work_projection_parts_work_part_ordinal",
        ),
    )
    op.create_index(
        "ix_external_channel_work_projection_parts_status_updated_at",
        "external_channel_work_projection_parts",
        ["status", "updated_at"],
        unique=False,
    )

    op.execute(
        sa.text(
            """
            INSERT INTO external_channel_works (
                id,
                binding_id,
                status,
                schema_version,
                title,
                tasks,
                state_revision,
                desired_progress_revision,
                desired_progress_payload,
                finished_at,
                created_at,
                updated_at
            )
            SELECT
                state.state_json ->> 'work_cycle_id',
                state.state_json ->> 'binding_id',
                (state.state_json ->> 'status')
                    ::external_channel_work_status,
                2,
                state.state_json ->> 'title',
                state.state_json -> 'tasks',
                (state.state_json ->> 'state_revision')::integer,
                (state.state_json ->> 'desired_progress_revision')::integer,
                state.state_json -> 'desired_progress',
                (state.state_json ->> 'finished_at')::timestamptz,
                state.created_at,
                state.updated_at
            FROM toolkit_states AS state
            WHERE state.toolkit_namespace = 'external_channel'
              AND state.state_name LIKE 'channel_work:%'
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO external_channel_work_projection_parts (
                id,
                work_id,
                part_ordinal,
                desired_progress_revision,
                status,
                provider_message_key,
                created_at,
                updated_at
            )
            SELECT
                md5(
                    (state.state_json ->> 'work_cycle_id')
                    || ':'
                    || (part.value ->> 'part_ordinal')
                ),
                state.state_json ->> 'work_cycle_id',
                (part.value ->> 'part_ordinal')::integer,
                (part.value ->> 'desired_progress_revision')::integer,
                (part.value ->> 'status')
                    ::external_channel_work_projection_status,
                part.value ->> 'provider_message_key',
                state.created_at,
                state.updated_at
            FROM toolkit_states AS state
            CROSS JOIN LATERAL jsonb_array_elements(
                COALESCE(
                    state.state_json -> 'projection_parts',
                    '[]'::jsonb
                )
            ) AS part(value)
            WHERE state.toolkit_namespace = 'external_channel'
              AND state.state_name LIKE 'channel_work:%'
            """
        )
    )
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE
                state_count bigint;
                work_count bigint;
            BEGIN
                SELECT count(*)
                INTO state_count
                FROM toolkit_states AS state
                WHERE state.toolkit_namespace = 'external_channel'
                  AND state.state_name LIKE 'channel_work:%';

                SELECT count(*)
                INTO work_count
                FROM external_channel_works;

                IF state_count <> work_count THEN
                    RAISE EXCEPTION
                        'External Channel Work downgrade count mismatch: % <> %',
                        state_count,
                        work_count;
                END IF;
            END
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM toolkit_states
            WHERE toolkit_namespace = 'external_channel'
              AND state_name LIKE 'channel_work:%'
            """
        )
    )
