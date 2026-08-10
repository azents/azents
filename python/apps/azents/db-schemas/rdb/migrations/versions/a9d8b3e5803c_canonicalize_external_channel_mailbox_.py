"""canonicalize external channel mailbox messages

Revision ID: a9d8b3e5803c
Revises: d0c984babbb1
Create Date: 2026-08-10 08:23:02.892701

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9d8b3e5803c"
down_revision: str | Sequence[str] | None = "d0c984babbb1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _require_no_rows(query: str, message: str) -> None:
    """Abort the migration when a fail-closed preflight query returns a row."""
    if op.get_bind().execute(sa.text(query)).first() is not None:
        raise RuntimeError(message)


def upgrade() -> None:
    """Upgrade schema and canonical persisted External Channel messages."""
    op.add_column(
        "mailbox_items",
        sa.Column("order_group", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "mailbox_items",
        sa.Column("order_sequence", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE mailbox_items
            SET order_group = id,
                order_sequence = 0
            """
        )
    )

    _require_no_rows(
        """
        SELECT id
        FROM mailbox_items
        WHERE kind::text = 'external_channel_invocation'
          AND (
              jsonb_typeof(payload) IS DISTINCT FROM 'object'
              OR payload ->> 'type' IS DISTINCT FROM 'external_channel_invocation'
              OR jsonb_typeof(payload -> 'items') IS DISTINCT FROM 'array'
              OR jsonb_array_length(payload -> 'items') = 0
              OR (
                  payload ? 'initial_title_eligible'
                  AND jsonb_typeof(payload -> 'initial_title_eligible')
                      IS DISTINCT FROM 'boolean'
              )
              OR EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements(payload -> 'items') WITH ORDINALITY
                       AS item(value, ordinal)
                  WHERE jsonb_typeof(item.value) IS DISTINCT FROM 'object'
                     OR COALESCE(
                         item.value ->> 'presentation_kind',
                         ''
                     ) NOT IN (
                         'system_reminder',
                         'external_channel_message'
                     )
                     OR (
                         item.value ->> 'presentation_kind' = 'system_reminder'
                         AND (
                             item.ordinal <> 1
                             OR item.value ->> 'item_key'
                                 IS DISTINCT FROM 'external_channel:0'
                         )
                     )
                     OR (
                         item.value ->> 'presentation_kind'
                             = 'external_channel_message'
                         AND (
                             jsonb_typeof(
                                 item.value #> ARRAY[
                                     'metadata',
                                     'external_channel_message'
                                 ]
                             ) IS DISTINCT FROM 'object'
                             OR COALESCE(
                                 item.value #>> ARRAY[
                                     'metadata',
                                     'external_channel_message',
                                     'authorization'
                                 ],
                                 ''
                             ) NOT IN (
                                 'context_only',
                                 'authorized_invocation'
                             )
                             OR item.value #> ARRAY[
                                 'metadata',
                                 'external_channel_message'
                             ] ? 'prompt_role'
                             OR COALESCE(
                                 item.value #>> ARRAY[
                                     'metadata',
                                     'external_channel_message',
                                     'invocation_batch_id'
                                 ],
                                 ''
                             ) = ''
                             OR COALESCE(
                                 item.value #>> ARRAY[
                                     'metadata',
                                     'external_channel_message',
                                     'provider_message_key'
                                 ],
                                 ''
                             ) = ''
                         )
                     )
              )
              OR (
                  SELECT count(*)
                  FROM jsonb_array_elements(payload -> 'items') AS item(value)
                  WHERE item.value ->> 'presentation_kind'
                      = 'external_channel_message'
              ) = 0
              OR (
                  SELECT count(*)
                  FROM jsonb_array_elements(payload -> 'items') AS item(value)
                  WHERE item.value ->> 'presentation_kind' = 'system_reminder'
              ) > 1
          )
        LIMIT 1
        """,
        "Legacy External Channel mailbox payload is malformed.",
    )
    _require_no_rows(
        """
        SELECT id
        FROM events
        WHERE kind::text = 'external_channel_message'
          AND (
              jsonb_typeof(payload) IS DISTINCT FROM 'object'
              OR COALESCE(payload ->> 'authorization', '') NOT IN (
                  'context_only',
                  'authorized_invocation'
              )
              OR payload ? 'prompt_role'
          )
        LIMIT 1
        """,
        "Legacy External Channel Event payload is malformed.",
    )

    op.execute(
        sa.text(
            """
            CREATE TEMP TABLE canonical_external_channel_mailbox_rows
            ON COMMIT DROP
            AS
            WITH messages AS (
                SELECT
                    mailbox.id AS original_id,
                    mailbox.kind,
                    mailbox.session_id,
                    mailbox.scheduling_mode,
                    mailbox.requested_model_target_label,
                    mailbox.requested_reasoning_effort,
                    mailbox.sender_user_id,
                    mailbox.created_at,
                    mailbox.payload,
                    item.value AS raw_item,
                    row_number() OVER (
                        PARTITION BY mailbox.id
                        ORDER BY item.ordinal
                    ) - 1 AS message_sequence,
                    EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements(mailbox.payload -> 'items')
                             AS reminder(value)
                        WHERE reminder.value ->> 'presentation_kind'
                            = 'system_reminder'
                    ) AS context_omitted
                FROM mailbox_items AS mailbox
                CROSS JOIN LATERAL jsonb_array_elements(mailbox.payload -> 'items')
                    WITH ORDINALITY AS item(value, ordinal)
                WHERE mailbox.kind::text = 'external_channel_invocation'
                  AND item.value ->> 'presentation_kind'
                      = 'external_channel_message'
            ),
            canonical AS (
                SELECT
                    messages.*,
                    raw_item #>> ARRAY[
                        'metadata',
                        'external_channel_message',
                        'invocation_batch_id'
                    ] AS invocation_id,
                    raw_item #>> ARRAY[
                        'metadata',
                        'external_channel_message',
                        'provider_message_key'
                    ] AS provider_message_key,
                    CASE raw_item #>> ARRAY[
                        'metadata',
                        'external_channel_message',
                        'authorization'
                    ]
                        WHEN 'authorized_invocation' THEN 'invocation'
                        ELSE 'context'
                    END AS prompt_role
                FROM messages
            )
            SELECT
                original_id,
                CASE
                    WHEN message_sequence = 0 THEN original_id
                    ELSE md5(original_id || ':' || message_sequence::text)
                END AS id,
                original_id AS order_group,
                message_sequence::integer AS order_sequence,
                kind,
                session_id,
                scheduling_mode,
                requested_model_target_label,
                requested_reasoning_effort,
                sender_user_id,
                'external-channel-message:' || md5(
                    length(invocation_id)::text
                    || ':'
                    || invocation_id
                    || provider_message_key
                ) AS idempotency_key,
                jsonb_build_object(
                    'type', 'external_channel_message',
                    'items', jsonb_build_array(
                        jsonb_set(
                            jsonb_set(
                                raw_item,
                                ARRAY['item_key'],
                                to_jsonb('external_channel_message:0'::text),
                                false
                            ),
                            ARRAY['metadata', 'external_channel_message'],
                            (
                                (
                                    raw_item #> ARRAY[
                                        'metadata',
                                        'external_channel_message'
                                    ]
                                ) - 'authorization'
                            ) || jsonb_build_object('prompt_role', prompt_role),
                            false
                        )
                    ),
                    'context_omitted',
                        context_omitted AND message_sequence = 0,
                    'initial_title_eligible',
                        COALESCE(
                            (payload ->> 'initial_title_eligible')::boolean,
                            false
                        ) AND prompt_role = 'invocation'
                ) AS payload,
                created_at
            FROM canonical
            """
        )
    )

    _require_no_rows(
        """
        SELECT candidate.id
        FROM canonical_external_channel_mailbox_rows AS candidate
        JOIN mailbox_items AS existing ON existing.id = candidate.id
        WHERE candidate.order_sequence > 0
        LIMIT 1
        """,
        "Split External Channel mailbox ID collides with an existing row.",
    )
    _require_no_rows(
        """
        SELECT idempotency_key
        FROM canonical_external_channel_mailbox_rows
        GROUP BY idempotency_key
        HAVING count(*) > 1
        LIMIT 1
        """,
        "External Channel provider-message idempotency keys collide.",
    )
    _require_no_rows(
        """
        SELECT candidate.idempotency_key
        FROM canonical_external_channel_mailbox_rows AS candidate
        JOIN mailbox_items AS existing
          ON existing.session_id = candidate.session_id
         AND existing.kind::text = 'external_channel_invocation'
         AND existing.idempotency_key = candidate.idempotency_key
         AND existing.id <> candidate.original_id
        LIMIT 1
        """,
        "External Channel provider-message identity conflicts with another row.",
    )

    op.execute(
        sa.text(
            """
            UPDATE mailbox_items AS mailbox
            SET idempotency_key = canonical.idempotency_key,
                order_group = canonical.order_group,
                order_sequence = canonical.order_sequence,
                payload = canonical.payload
            FROM canonical_external_channel_mailbox_rows AS canonical
            WHERE canonical.original_id = mailbox.id
              AND canonical.order_sequence = 0
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO mailbox_items (
                id,
                session_id,
                kind,
                scheduling_mode,
                requested_model_target_label,
                requested_reasoning_effort,
                sender_user_id,
                idempotency_key,
                order_group,
                order_sequence,
                payload,
                created_at
            )
            SELECT
                id,
                session_id,
                kind,
                scheduling_mode,
                requested_model_target_label,
                requested_reasoning_effort,
                sender_user_id,
                idempotency_key,
                order_group,
                order_sequence,
                payload,
                created_at
            FROM canonical_external_channel_mailbox_rows
            WHERE order_sequence > 0
            ORDER BY order_group, order_sequence
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE events
            SET payload = (
                payload - 'authorization'
            ) || jsonb_build_object(
                'prompt_role',
                CASE payload ->> 'authorization'
                    WHEN 'authorized_invocation' THEN 'invocation'
                    ELSE 'context'
                END
            )
            WHERE kind::text = 'external_channel_message'
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TYPE mailbox_item_kind
            RENAME VALUE 'external_channel_invocation'
            TO 'external_channel_message'
            """
        )
    )

    op.alter_column("mailbox_items", "order_group", nullable=False)
    op.alter_column("mailbox_items", "order_sequence", nullable=False)
    op.create_check_constraint(
        "ck_mailbox_items_order_sequence",
        "mailbox_items",
        "order_sequence >= 0",
    )
    op.drop_index("ix_mailbox_items_session_id_id", table_name="mailbox_items")
    op.create_index(
        "ix_mailbox_items_session_order",
        "mailbox_items",
        ["session_id", "order_group", "order_sequence", "id"],
    )

    _require_no_rows(
        """
        SELECT id
        FROM mailbox_items
        WHERE kind::text = 'external_channel_message'
          AND (
              payload ->> 'type' IS DISTINCT FROM 'external_channel_message'
              OR jsonb_typeof(payload -> 'items') IS DISTINCT FROM 'array'
              OR jsonb_array_length(payload -> 'items') <> 1
              OR payload #>> ARRAY['items', '0', 'item_key']
                  IS DISTINCT FROM 'external_channel_message:0'
              OR payload #>> ARRAY['items', '0', 'presentation_kind']
                  IS DISTINCT FROM 'external_channel_message'
              OR payload #> ARRAY[
                  'items',
                  '0',
                  'metadata',
                  'external_channel_message'
              ] ? 'authorization'
              OR COALESCE(
                  payload #>> ARRAY[
                      'items',
                      '0',
                      'metadata',
                      'external_channel_message',
                      'prompt_role'
                  ],
                  ''
              ) NOT IN ('context', 'invocation')
          )
        LIMIT 1
        """,
        "Canonical External Channel mailbox validation failed.",
    )
    _require_no_rows(
        """
        SELECT id
        FROM events
        WHERE kind::text = 'external_channel_message'
          AND (
              payload ? 'authorization'
              OR COALESCE(payload ->> 'prompt_role', '')
                  NOT IN ('context', 'invocation')
          )
        LIMIT 1
        """,
        "Canonical External Channel Event validation failed.",
    )


def downgrade() -> None:
    """Restore the prior schema only when no canonical mailbox rows remain."""
    _require_no_rows(
        """
        SELECT id
        FROM mailbox_items
        WHERE kind::text = 'external_channel_message'
        LIMIT 1
        """,
        "Downgrade with canonical External Channel mailbox data is unsupported.",
    )
    op.execute(
        sa.text(
            """
            UPDATE events
            SET payload = (
                payload - 'prompt_role'
            ) || jsonb_build_object(
                'authorization',
                CASE payload ->> 'prompt_role'
                    WHEN 'invocation' THEN 'authorized_invocation'
                    ELSE 'context_only'
                END
            )
            WHERE kind::text = 'external_channel_message'
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TYPE mailbox_item_kind
            RENAME VALUE 'external_channel_message'
            TO 'external_channel_invocation'
            """
        )
    )
    op.drop_index("ix_mailbox_items_session_order", table_name="mailbox_items")
    op.create_index(
        "ix_mailbox_items_session_id_id",
        "mailbox_items",
        ["session_id", "id"],
    )
    op.drop_constraint(
        "ck_mailbox_items_order_sequence",
        "mailbox_items",
        type_="check",
    )
    op.drop_column("mailbox_items", "order_sequence")
    op.drop_column("mailbox_items", "order_group")
