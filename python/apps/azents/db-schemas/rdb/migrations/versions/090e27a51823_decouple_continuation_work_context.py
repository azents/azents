"""Preserve admitted work independently of execution-segment host bindings."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "090e27a51823"
down_revision: str | Sequence[str] | None = "2a9be235de5d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Materialize exact context before removing domain-specific Run authority."""
    op.execute("""
        UPDATE toolkit_states
        SET state_json = state_json || jsonb_build_object(
            'goal_id', CASE WHEN state_json->>'objective' IS NOT NULL
                THEN replace(gen_random_uuid()::text, '-', '') ELSE NULL END
        )
        WHERE toolkit_namespace = 'goal' AND state_name = 'goal'
    """)
    # Old promoted reminders retained only text. If their terminal operation
    # provenance was pruned, no canonical successor/source link can be invented.
    op.execute("""
        DO $migration$
        BEGIN
            IF EXISTS (
                WITH RECURSIVE live_lineage AS (
                    SELECT r.id, r.session_id, r.run_index
                    FROM agent_runs r
                    WHERE r.status::text IN ('pending','running')
                       OR EXISTS (
                           SELECT 1 FROM conversations c
                           WHERE c.session_id = r.session_id
                             AND c.pending_idle_continuation_run_id = r.id
                       )
                       OR EXISTS (
                           SELECT 1 FROM mailbox_items m
                           WHERE m.session_id = r.session_id
                             AND r.status::text = 'completed'
                             AND (
                                 (m.kind::text = 'turn_action_continuation'
                                  AND m.payload->>'predecessor_run_id' = r.id)
                                 OR (
                                     m.kind::text IN (
                                         'goal_continuation',
                                         'external_channel_continuation',
                                         'scheduled_task_continuation',
                                         'routine_continuation'
                                     )
                                     AND m.idempotency_key
                                         LIKE 'idle_continuation:%'
                                     AND split_part(
                                         m.idempotency_key, ':', 2
                                     ) = r.id
                                 )
                             )
                       )
                    UNION
                    SELECT source.id, source.session_id, source.run_index
                    FROM live_lineage target
                    JOIN agent_run_input_events i ON i.agent_run_id = target.id
                    JOIN events reminder ON reminder.id = i.event_id
                      AND reminder.session_id = target.session_id
                    JOIN events terminal ON terminal.session_id = target.session_id
                      AND terminal.external_id = replace(
                          reminder.external_id, 'turn_action_continuation:',
                          'action_execution_result:'
                      )
                    JOIN agent_runs source ON source.id = terminal.payload#>>
                        '{action_execution,execution,action,originating_run_id}'
                      AND source.session_id = target.session_id
                      AND source.run_index < target.run_index
                      AND source.status::text = 'completed'
                    WHERE reminder.kind::text = 'system_reminder'
                      AND reminder.external_id LIKE 'turn_action_continuation:%'
                )
                SELECT 1 FROM agent_runs target
                JOIN live_lineage live ON live.id = target.id
                JOIN agent_run_input_events i ON i.agent_run_id = target.id
                JOIN events reminder ON reminder.id = i.event_id
                WHERE reminder.kind::text = 'system_reminder'
                  AND reminder.external_id LIKE 'turn_action_continuation:%'
                  AND NOT EXISTS (
                      SELECT 1 FROM events terminal
                      WHERE terminal.session_id = target.session_id
                        AND terminal.external_id = replace(
                            reminder.external_id, 'turn_action_continuation:',
                            'action_execution_result:'
                        )
                  )
                  AND EXISTS (
                      SELECT 1 FROM toolkit_states s
                      JOIN agent_runs source
                        ON source.id = s.state_json->>'current_run_id'
                       AND source.session_id = target.session_id
                      WHERE s.session_id = target.session_id
                        AND source.status::text IN ('pending','running','completed')
                        AND source.run_index < target.run_index
                        AND s.state_json->>'phase' = 'started'
                        AND (
                            (s.toolkit_namespace = 'scheduled'
                             AND s.state_name LIKE 'cycle:%')
                            OR (s.toolkit_namespace = 'routines'
                                AND s.state_name LIKE 'execution:%')
                        )
                  )
            ) THEN
                RAISE EXCEPTION 'Cannot migrate active continuation work: '
                    'canonical bridge provenance is unavailable';
            END IF;
        END $migration$;
    """)
    op.add_column(
        "agent_runs",
        sa.Column(
            "work_context",
            JSONB(),
            nullable=False,
            server_default=sa.text(
                "jsonb_build_object('scheduled_cycle_ids', '[]'::jsonb, "
                "'routine_executions', '[]'::jsonb, 'unrelated_input', false)"
            ),
        ),
    )
    op.execute("""
        UPDATE agent_runs r
        SET work_context = jsonb_build_object(
            'scheduled_cycle_ids', CASE
                WHEN r.scheduled_task_cycle_id IS NULL THEN '[]'::jsonb
                ELSE jsonb_build_array(r.scheduled_task_cycle_id) END,
            'routine_executions', '[]'::jsonb,
            'unrelated_input', EXISTS(
                SELECT 1 FROM agent_run_input_events i
                JOIN events e ON e.id = i.event_id AND e.session_id = r.session_id
                WHERE i.agent_run_id = r.id
                  AND e.kind::text NOT IN (
                      'routine_trigger', 'routine_continuation',
                      'scheduled_task_trigger', 'scheduled_task_continuation'
                  )
                  AND NOT (
                      e.kind::text = 'system_reminder'
                      AND e.external_id LIKE 'turn_action_continuation:%'
                  )
            )
        )
    """)
    # Retained occurrence state remains canonical even if its input Event was
    # compacted. Do not grant authority from an old, replaced input reference.
    op.execute("""
        UPDATE agent_runs r
        SET work_context = jsonb_set(
            r.work_context, '{routine_executions}', seeds.refs
        )
        FROM (
            SELECT s.session_id, s.state_json->>'current_run_id' AS run_id,
                   jsonb_agg(jsonb_build_object(
                       'routine_id',
                           s.state_json#>>'{context,candidate,routine_id}',
                       'execution_id', s.state_json#>>'{context,execution_id}',
                       'slug', s.state_json#>>'{context,candidate,slug}',
                       'title', s.state_json#>>'{context,candidate,content,title}'
                   ) ORDER BY s.state_name) AS refs
            FROM toolkit_states s
            WHERE s.toolkit_namespace = 'routines'
              AND s.state_name LIKE 'execution:%'
              AND s.state_json->>'phase' IN ('started','completed')
              AND s.state_json->>'current_run_id' IS NOT NULL
            GROUP BY s.session_id, s.state_json->>'current_run_id'
        ) seeds
        WHERE r.id = seeds.run_id AND r.session_id = seeds.session_id
    """)
    op.execute("""
        UPDATE agent_runs r
        SET work_context = jsonb_set(
            r.work_context, '{scheduled_cycle_ids}',
            (SELECT jsonb_agg(DISTINCT v.value ORDER BY v.value)
             FROM jsonb_array_elements(
                 (r.work_context->'scheduled_cycle_ids') || seeds.refs
             ) v)
        )
        FROM (
            SELECT s.session_id, s.state_json->>'current_run_id' AS run_id,
                   jsonb_agg(s.state_json->'cycle_id') AS refs
            FROM toolkit_states s
            WHERE s.toolkit_namespace = 'scheduled'
              AND s.state_name LIKE 'cycle:%'
              AND s.state_json->>'phase' = 'started'
              AND s.state_json->>'current_run_id' IS NOT NULL
            GROUP BY s.session_id, s.state_json->>'current_run_id'
        ) seeds
        WHERE r.id = seeds.run_id AND r.session_id = seeds.session_id
    """)
    # Missing old input evidence was never a Routine-only archive grant. New
    # execution preserves provenance before retention, but legacy absence cannot
    # be relabeled as proof that no ordinary input was consumed.
    op.execute("""
        UPDATE agent_runs r SET work_context = jsonb_set(
            r.work_context, '{unrelated_input}', 'true'::jsonb
        )
        WHERE jsonb_array_length(r.work_context->'routine_executions') > 0
          AND NOT EXISTS (
              SELECT 1 FROM agent_run_input_events i WHERE i.agent_run_id = r.id
          )
    """)
    # A retry's canonical shared original inputs identify only earlier sources.
    # Bridge reminders identify their source through the terminal operation.
    op.execute("""
        DO $migration$
        DECLARE changed integer;
        BEGIN
            LOOP
                WITH edges AS (
                    SELECT target.id AS target_id, source.id AS source_id
                    FROM agent_runs target
                    JOIN agent_run_input_events i ON i.agent_run_id = target.id
                    JOIN events reminder ON reminder.id = i.event_id
                    JOIN events terminal ON terminal.session_id = target.session_id
                      AND terminal.external_id = replace(
                          reminder.external_id, 'turn_action_continuation:',
                          'action_execution_result:'
                      )
                    JOIN agent_runs source ON source.id = terminal.payload#>>
                        '{action_execution,execution,action,originating_run_id}'
                      AND source.session_id = target.session_id
                      AND source.run_index < target.run_index
                    WHERE reminder.kind::text = 'system_reminder'
                      AND reminder.external_id LIKE 'turn_action_continuation:%'
                    UNION
                    SELECT target.id, source.id
                    FROM agent_runs target
                    JOIN agent_run_input_events ti ON ti.agent_run_id = target.id
                    JOIN agent_run_input_events si ON si.event_id = ti.event_id
                    JOIN agent_runs source ON source.id = si.agent_run_id
                      AND source.session_id = target.session_id
                      AND source.run_index < target.run_index
                    JOIN events e ON e.id = ti.event_id
                    WHERE e.kind::text IN (
                        'scheduled_task_trigger','scheduled_task_continuation'
                    )
                ), sources AS (
                    SELECT edges.target_id, jsonb_agg(source.work_context) AS contexts
                    FROM edges JOIN agent_runs source ON source.id = edges.source_id
                    GROUP BY edges.target_id
                ), merged AS (
                    SELECT r.id, jsonb_build_object(
                        'scheduled_cycle_ids', COALESCE((
                            SELECT jsonb_agg(DISTINCT v.value ORDER BY v.value)
                            FROM jsonb_array_elements(
                                sources.contexts || jsonb_build_array(r.work_context)
                            ) c
                            CROSS JOIN LATERAL jsonb_array_elements(
                                c.value->'scheduled_cycle_ids'
                            ) v
                        ), '[]'::jsonb),
                        'routine_executions', COALESCE((
                            SELECT jsonb_agg(DISTINCT v.value ORDER BY v.value)
                            FROM jsonb_array_elements(
                                sources.contexts || jsonb_build_array(r.work_context)
                            ) c
                            CROSS JOIN LATERAL jsonb_array_elements(
                                c.value->'routine_executions'
                            ) v
                        ), '[]'::jsonb),
                        'unrelated_input', (
                            SELECT bool_or((c.value->>'unrelated_input')::boolean)
                            FROM jsonb_array_elements(
                                sources.contexts || jsonb_build_array(r.work_context)
                            ) c
                        )
                    ) AS context
                    FROM agent_runs r JOIN sources ON sources.target_id = r.id
                )
                UPDATE agent_runs r SET work_context = merged.context
                FROM merged WHERE r.id = merged.id
                  AND r.work_context IS DISTINCT FROM merged.context;
                GET DIAGNOSTICS changed = ROW_COUNT;
                EXIT WHEN changed = 0;
            END LOOP;
        END $migration$;
    """)
    op.execute("""
        UPDATE mailbox_items
        SET payload = payload || jsonb_build_object(
            'source_run_id', split_part(idempotency_key, ':', 2)
        )
        WHERE kind::text IN (
            'goal_continuation','external_channel_continuation',
            'scheduled_task_continuation','routine_continuation'
        ) AND idempotency_key LIKE 'idle_continuation:%'
    """)
    op.execute("""
        UPDATE toolkit_states SET state_json = state_json - 'current_run_id'
        WHERE (toolkit_namespace = 'scheduled' AND state_name LIKE 'cycle:%')
           OR (toolkit_namespace = 'routines' AND state_name LIKE 'execution:%')
    """)
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    op.drop_column("agent_runs", "scheduled_task_cycle_id")
    op.alter_column("agent_runs", "work_context", server_default=None)


def downgrade() -> None:
    """Reject rollback that would discard independently carried work authority."""
    raise RuntimeError(
        "This migration is irreversible: prior Run host bindings cannot represent "
        "independent continuation work contexts without losing authority."
    )
