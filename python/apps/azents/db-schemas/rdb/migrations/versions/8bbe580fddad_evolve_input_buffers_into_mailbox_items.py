"""evolve input buffers into mailbox items

Revision ID: 8bbe580fddad
Revises: 32c9f7dbbe18
Create Date: 2026-07-26 04:50:16.185672

"""

import copy
import json
from typing import Sequence, cast

import sqlalchemy as sa
from alembic import op
from pydantic import TypeAdapter
from sqlalchemy.dialects import postgresql

from azents.core.enums import (
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    MailboxItemKind,
)
from azents.core.external_channel_file import add_external_channel_file_locators
from azents.engine.events.types import ExternalChannelMessagePayload
from azents.repos.mailbox.data import (
    MailboxEnvelopePayload,
)

_MAILBOX_PAYLOAD_ADAPTER = TypeAdapter(MailboxEnvelopePayload)

revision: str = "8bbe580fddad"
down_revision: str | Sequence[str] | None = "32c9f7dbbe18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rename_if_exists(table: str, old: str, new: str) -> None:
    op.execute(sa.text(f"ALTER TABLE IF EXISTS {table} RENAME COLUMN {old} TO {new}"))


def _rename_index_if_exists(old: str, new: str) -> None:
    op.execute(sa.text(f"ALTER INDEX IF EXISTS {old} RENAME TO {new}"))


def _rename_constraint_if_exists(table: str, old: str, new: str) -> None:
    inspector = sa.inspect(op.get_bind())
    names = {
        constraint["name"] for constraint in inspector.get_unique_constraints(table)
    }
    primary_key = inspector.get_pk_constraint(table).get("name")
    if primary_key is not None:
        names.add(primary_key)
    names.update(
        foreign_key["name"] for foreign_key in inspector.get_foreign_keys(table)
    )
    names.update(check["name"] for check in inspector.get_check_constraints(table))
    if old in names:
        op.execute(sa.text(f"ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new}"))


def _external_reference_mappings(value: object) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for category in ("users", "channels"):
        entries = value.get(category)
        if not isinstance(entries, dict):
            continue
        normalized = {
            str(key): str(label)
            for key, label in entries.items()
            if isinstance(key, str) and key and isinstance(label, str) and label
        }
        if normalized:
            result[category] = normalized
    return result


def _external_lifecycle(
    revision_kind: ExternalChannelMessageRevisionKind,
) -> ExternalChannelMessageLifecycle:
    return {
        ExternalChannelMessageRevisionKind.ORIGINAL: (
            ExternalChannelMessageLifecycle.CURRENT
        ),
        ExternalChannelMessageRevisionKind.EDIT: ExternalChannelMessageLifecycle.EDITED,
        ExternalChannelMessageRevisionKind.DELETE: (
            ExternalChannelMessageLifecycle.DELETED
        ),
    }[revision_kind]


def _normalize_external_file_locators(bind: sa.Connection) -> None:
    """Apply the runtime locator encoder to every external payload snapshot."""
    rows = list(
        bind.execute(sa.text("SELECT id, payload FROM mailbox_items")).mappings()
    )
    for row in rows:
        raw_payload = copy.deepcopy(row["payload"])
        payload = _MAILBOX_PAYLOAD_ADAPTER.validate_python(raw_payload)
        if payload.type != MailboxItemKind.EXTERNAL_CHANNEL_INVOCATION.value:
            continue
        if not isinstance(raw_payload, dict):
            raise ValueError(f"Mailbox payload is malformed for row {row['id']}")
        raw_items = raw_payload.get("items")
        if not isinstance(raw_items, list):
            raise ValueError(f"Mailbox payload items are malformed for row {row['id']}")
        changed = False
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise ValueError(
                    f"Mailbox payload item is malformed for row {row['id']}"
                )
            raw_metadata = raw_item.get("metadata")
            if not isinstance(raw_metadata, dict):
                raise ValueError(f"Mailbox metadata is malformed for row {row['id']}")
            raw_message = raw_metadata.get("external_channel_message")
            message = ExternalChannelMessagePayload.model_validate(raw_message)
            enriched = add_external_channel_file_locators(
                message.attachment_metadata,
                binding_id=message.binding_id,
            )
            if enriched != message.attachment_metadata:
                raw_message = cast(dict[str, object], raw_message)
                raw_message["attachment_metadata"] = enriched
                raw_metadata["external_channel_message"] = raw_message
                changed = True
        if changed:
            bind.execute(
                sa.text(
                    "UPDATE mailbox_items "
                    "SET payload = CAST(:payload AS jsonb) WHERE id = :id"
                ),
                {"payload": json.dumps(raw_payload), "id": row["id"]},
            )


def _validate_payload_rows(bind: sa.Connection) -> None:
    """Validate persisted JSON with the same adapters used by repositories."""
    rows = bind.execute(
        sa.text("SELECT id, kind::text AS kind, payload FROM mailbox_items")
    ).mappings()
    for row in rows:
        payload = _MAILBOX_PAYLOAD_ADAPTER.validate_python(row["payload"])
        if payload.type != row["kind"]:
            raise ValueError(f"Mailbox payload discriminator mismatch for {row['id']}")
        if payload.type != MailboxItemKind.EXTERNAL_CHANNEL_INVOCATION.value:
            continue
        expected_item_keys = [
            f"external_channel:{index}" for index in range(len(payload.items))
        ]
        actual_item_keys = [item.item_key for item in payload.items]
        if actual_item_keys != expected_item_keys:
            raise ValueError(
                f"External invocation sequence is not contiguous for mailbox row "
                f"{row['id']}"
            )
        for item in payload.items:
            raw_message = item.metadata.get("external_channel_message")
            message = ExternalChannelMessagePayload.model_validate(raw_message)
            expected_lifecycle = _external_lifecycle(message.revision_kind)
            if message.lifecycle is not expected_lifecycle:
                raise ValueError(
                    f"Invalid external lifecycle for mailbox row {row['id']}"
                )
            expected_mappings = _external_reference_mappings(message.reference_mappings)
            if expected_mappings != message.reference_mappings:
                raise ValueError(
                    f"Invalid external reference mappings for mailbox row {row['id']}"
                )
            if message.revision_kind is not ExternalChannelMessageRevisionKind.ORIGINAL:
                if not message.correction_of_revision_id:
                    raise ValueError(
                        f"Missing correction provenance for mailbox row {row['id']}"
                    )
            files = message.attachment_metadata.get("files")
            if isinstance(files, list):
                for file_item in files:
                    if not isinstance(file_item, dict):
                        continue
                    if file_item.get("provider_file_id") and not str(
                        file_item.get("file", "")
                    ).startswith("external-file:v1:"):
                        raise ValueError(
                            f"Missing external file locator for mailbox row {row['id']}"
                        )


def upgrade() -> None:
    """Rename the persistence boundary and materialize typed payload snapshots."""
    op.execute(sa.text("ALTER TABLE IF EXISTS input_buffers RENAME TO mailbox_items"))
    op.execute(
        sa.text("ALTER TYPE IF EXISTS input_buffer_kind RENAME TO mailbox_item_kind")
    )
    op.execute(
        sa.text(
            "ALTER TYPE IF EXISTS input_buffer_scheduling_mode "
            "RENAME TO mailbox_item_scheduling_mode"
        )
    )

    _rename_if_exists(
        "external_channel_invocation_batches", "input_buffer_id", "mailbox_item_id"
    )
    _rename_if_exists("action_executions", "input_buffer_id", "mailbox_item_id")
    _rename_if_exists(
        "agent_runs", "parent_result_input_buffer_id", "parent_result_mailbox_item_id"
    )

    for old, new in (
        ("ix_input_buffers_session_id", "ix_mailbox_items_session_id"),
        ("ix_input_buffers_session_id_id", "ix_mailbox_items_session_id_id"),
        (
            "ix_input_buffers_session_id_scheduling_mode",
            "ix_mailbox_items_session_id_scheduling_mode",
        ),
        ("ix_input_buffers_kind", "ix_mailbox_items_kind"),
        (
            "uq_input_buffers_session_kind_idempotency",
            "uq_mailbox_items_session_kind_idempotency",
        ),
        (
            "uq_input_buffers_runtime_kind_idempotency",
            "uq_mailbox_items_session_kind_idempotency",
        ),
        (
            "ix_action_executions_session_id_input_buffer_id",
            "ix_action_executions_session_id_mailbox_item_id",
        ),
        (
            "uq_action_executions_input_buffer_id",
            "uq_action_executions_mailbox_item_id",
        ),
    ):
        _rename_index_if_exists(old, new)

    for table, old, new in (
        ("mailbox_items", "pk_input_buffers", "pk_mailbox_items"),
        (
            "mailbox_items",
            "fk_input_buffers_session_id_agent_sessions",
            "fk_mailbox_items_session_id_agent_sessions",
        ),
        (
            "mailbox_items",
            "fk_input_buffers_sender_user_id_users",
            "fk_mailbox_items_sender_user_id_users",
        ),
        (
            "external_channel_invocation_batches",
            "external_channel_invocation_batches_input_buffer_id_fkey",
            "fk_external_channel_invocation_batches_mailbox_item_id_mailbox_items",
        ),
        (
            "mailbox_items",
            "ck_input_buffers_requested_profile",
            "ck_mailbox_items_requested_profile",
        ),
        (
            "mailbox_items",
            "ck_input_buffers_sender_user_kind",
            "ck_mailbox_items_sender_user_kind",
        ),
    ):
        _rename_constraint_if_exists(table, old, new)

    op.add_column(
        "mailbox_items",
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM mailbox_items m
                    WHERE m.kind::text = 'external_channel_invocation'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM external_channel_invocation_batches b
                          JOIN external_channel_invocation_batch_items bi
                            ON bi.batch_id = b.id
                          WHERE b.mailbox_item_id = m.id
                      )
                ) THEN
                    RAISE EXCEPTION
                        'Cannot backfill external mailbox payload without batch items';
                END IF;
            END $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM external_channel_invocation_batches b
                    JOIN mailbox_items m
                        ON m.id = b.mailbox_item_id
                    JOIN external_channel_bindings binding
                        ON binding.id = b.binding_id
                    JOIN external_channel_resources resource
                        ON resource.id = binding.resource_id
                    WHERE m.kind::text = 'external_channel_invocation'
                      AND (
                          resource.provider_resource_key IS NULL
                          OR btrim(resource.provider_resource_key) = ''
                          OR jsonb_typeof(resource.labels) <> 'object'
                          OR COALESCE(
                              NULLIF(resource.labels->>'channel_id', ''),
                              NULLIF(resource.labels->>'channel_name', '')
                          ) IS NULL
                          OR (
                              resource.labels ? 'thread_ts'
                              AND jsonb_typeof(resource.labels->'thread_ts')
                                  NOT IN ('string', 'null')
                          )
                      )
                ) THEN
                    RAISE EXCEPTION
                        'Cannot backfill external mailbox payload: '
                        'malformed resource identity';
                END IF;
            END $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE mailbox_items AS m
            SET payload = jsonb_build_object(
                'type', 'external_channel_invocation',
                'items', projection.items
            )
            FROM (
                SELECT
                    b.mailbox_item_id,
                    jsonb_agg(
                        jsonb_build_object(
                            'item_key', 'external_channel:' || bi.sequence::text,
                            'presentation_kind', 'external_channel_message',
                            'content', COALESCE(r.normalized_body, ''),
                            'metadata', jsonb_build_object(
                                'external_channel_message', jsonb_build_object(
                                    'provider', c.provider::text,
                                    'provider_tenant_id', c.provider_tenant_id,
                                    'resource_id', msg.resource_id,
                                    'resource_label', COALESCE(
                                        resource.labels->>'channel_id',
                                        resource.labels->>'channel_name',
                                        resource.provider_resource_key
                                    ),
                                    'resource_type', resource.resource_type::text,
                                    'binding_id', b.binding_id,
                                    'invocation_batch_id', b.id,
                                    'external_message_id', msg.id,
                                    'revision_id', r.id,
                                    'revision_kind', r.revision_kind::text,
                                    'projection_root_id',
                                        'external-channel:' || b.binding_id || ':'
                                        || msg.id,
                                    'provider_message_key', msg.provider_message_key,
                                    'provider_position', msg.provider_position,
                                    'principal_id', msg.principal_id,
                                    'provider_user_id', principal.provider_user_id,
                                    'sender_display_name', principal.display_name,
                                    'author_type', msg.author_type::text,
                                    'authorization', CASE
                                        WHEN msg.id = b.trigger_message_id
                                        THEN 'authorized_invocation'
                                        ELSE 'context_only'
                                    END,
                                    'lifecycle', CASE
                                        WHEN r.revision_kind::text = 'delete'
                                        THEN 'deleted'
                                        WHEN r.revision_kind::text = 'edit'
                                        THEN 'edited'
                                        ELSE 'current'
                                    END,
                                    'body', r.normalized_body,
                                    'attachment_metadata', CASE
                                        WHEN jsonb_typeof(
                                            r.attachment_metadata->'files'
                                        ) = 'array'
                                        THEN jsonb_set(
                                            COALESCE(
                                                r.attachment_metadata, '{}'::jsonb
                                            ),
                                            '{files}',
                                            (
                                                SELECT jsonb_agg(
                                                    CASE
                                                        WHEN file_item->>'provider'
                                                            IS NOT NULL
                                                         AND file_item->>
                                                            'provider_file_id'
                                                            IS NOT NULL
                                                        THEN file_item
                                                            || jsonb_build_object(
                                                                'file', concat(
                                                                    'external-file:v1:',
                                                                    c.provider::text,
                                                                    ':',
                                                                    b.binding_id,
                                                                    ':',
                                                                    file_item->>
                                                                        'provider_file_id'
                                                                )
                                                        )
                                                        ELSE file_item
                                                    END
                                                )
                                                FROM jsonb_array_elements(
                                                    r.attachment_metadata->'files'
                                                ) AS file_item
                                            )
                                        )
                                        ELSE COALESCE(
                                            r.attachment_metadata, '{}'::jsonb
                                        )
                                    END,
                                    'reference_mappings',
                                        COALESCE(r.reference_mappings, '{}'::jsonb),
                                    'provider_created_at', msg.provider_created_at,
                                    'provider_updated_at', msg.provider_updated_at,
                                    'original_url', msg.original_url,
                                    'truncated_context_message_count',
                                        b.truncation_message_count,
                                    'truncated_context_size', b.truncation_size,
                                    'correction_of_revision_id', CASE
                                        WHEN r.revision_kind::text = 'original'
                                        THEN NULL
                                        ELSE (
                                            SELECT original.id
                                            FROM external_channel_message_revisions
                                                original
                                            WHERE original.message_id = msg.id
                                              AND original.revision_kind::text =
                                                'original'
                                            ORDER BY original.created_at, original.id
                                            LIMIT 1
                                        )
                                    END
                                )
                            )
                        )
                        ORDER BY bi.sequence, bi.id
                    ) AS items
                FROM external_channel_invocation_batches b
                JOIN external_channel_invocation_batch_items bi
                    ON bi.batch_id = b.id
                JOIN external_channel_message_revisions r
                    ON r.id = bi.message_revision_id
                JOIN external_channel_messages msg
                    ON msg.id = r.message_id
                JOIN external_channel_bindings binding
                    ON binding.id = b.binding_id
                JOIN external_channel_resources resource
                    ON resource.id = binding.resource_id
                JOIN external_channel_connections c
                    ON c.id = resource.connection_id
                LEFT JOIN external_channel_principals principal
                    ON principal.id = msg.principal_id
                GROUP BY b.mailbox_item_id
            ) AS projection
            WHERE m.id = projection.mailbox_item_id
              AND m.kind::text = 'external_channel_invocation'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE mailbox_items
            SET payload = jsonb_build_object(
                'type', kind::text,
                'items', jsonb_build_array(jsonb_build_object(
                    'item_key', kind::text || ':0',
                    'presentation_kind', kind::text,
                    'content', content,
                    'metadata', COALESCE(metadata, '{}'::jsonb),
                    'action', action,
                    'attachments', COALESCE(attachments, '[]'::jsonb),
                    'file_parts', COALESCE(file_parts, '[]'::jsonb)
                ))
            )
            WHERE payload IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM mailbox_items WHERE payload IS NULL) THEN
                    RAISE EXCEPTION
                        'Cannot complete mailbox payload backfill: '
                        'malformed mailbox row';
                END IF;
                IF EXISTS (
                    SELECT 1
                    FROM mailbox_items
                    WHERE payload->>'type' <> kind::text
                ) THEN
                    RAISE EXCEPTION
                        'Cannot complete mailbox payload backfill: '
                        'kind discriminator mismatch';
                END IF;
                IF EXISTS (
                    SELECT 1
                    FROM mailbox_items
                    WHERE kind::text = 'external_channel_invocation'
                      AND (
                          jsonb_array_length(payload->'items') = 0
                          OR EXISTS (
                              SELECT 1
                              FROM jsonb_array_elements(payload->'items') item
                              WHERE item->'metadata'->'external_channel_message'
                                IS NULL
                          )
                      )
                ) THEN
                    RAISE EXCEPTION
                        'Cannot complete external mailbox payload validation';
                END IF;
            END $$;
            """
        )
    )
    _normalize_external_file_locators(op.get_bind())
    _validate_payload_rows(op.get_bind())
    for column in ("content", "metadata", "action", "attachments", "file_parts"):
        op.drop_column("mailbox_items", column)
    op.alter_column("mailbox_items", "payload", nullable=False)


def downgrade() -> None:
    """Restore legacy names before any new payloads are admitted."""
    op.add_column("mailbox_items", sa.Column("content", sa.Text(), nullable=True))
    op.add_column(
        "mailbox_items",
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "mailbox_items",
        sa.Column("action", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "mailbox_items",
        sa.Column(
            "attachments", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column(
        "mailbox_items",
        sa.Column("file_parts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE mailbox_items
            SET content = COALESCE(payload->'items'->0->>'content', ''),
                metadata = CASE
                    WHEN kind::text = 'external_channel_invocation' THEN
                        jsonb_build_object(
                            'external_channel_invocation_batch_id',
                            payload->'items'->0->'metadata'
                                ->'external_channel_message'
                                ->>'invocation_batch_id'
                        )
                    ELSE COALESCE(payload->'items'->0->'metadata', '{}'::jsonb)
                END,
                action = payload->'items'->0->'action',
                attachments = COALESCE(
                    payload->'items'->0->'attachments', '[]'::jsonb
                ),
                file_parts = COALESCE(
                    payload->'items'->0->'file_parts', '[]'::jsonb
                )
            """
        )
    )
    op.alter_column("mailbox_items", "content", nullable=False)
    op.alter_column("mailbox_items", "metadata", nullable=False)
    op.alter_column("mailbox_items", "attachments", nullable=False)
    op.alter_column("mailbox_items", "file_parts", nullable=False)
    op.drop_column("mailbox_items", "payload")
    for old, new in (
        ("ix_mailbox_items_session_id", "ix_input_buffers_session_id"),
        ("ix_mailbox_items_session_id_id", "ix_input_buffers_session_id_id"),
        (
            "ix_mailbox_items_session_id_scheduling_mode",
            "ix_input_buffers_session_id_scheduling_mode",
        ),
        ("ix_mailbox_items_kind", "ix_input_buffers_kind"),
        (
            "uq_mailbox_items_session_kind_idempotency",
            "uq_input_buffers_session_kind_idempotency",
        ),
        (
            "ix_action_executions_session_id_mailbox_item_id",
            "ix_action_executions_session_id_input_buffer_id",
        ),
        (
            "uq_action_executions_mailbox_item_id",
            "uq_action_executions_input_buffer_id",
        ),
    ):
        _rename_index_if_exists(old, new)
    for table, old, new in (
        ("mailbox_items", "pk_mailbox_items", "pk_input_buffers"),
        (
            "mailbox_items",
            "fk_mailbox_items_session_id_agent_sessions",
            "fk_input_buffers_session_id_agent_sessions",
        ),
        (
            "mailbox_items",
            "fk_mailbox_items_sender_user_id_users",
            "fk_input_buffers_sender_user_id_users",
        ),
        (
            "external_channel_invocation_batches",
            "fk_external_channel_invocation_batches_mailbox_item_id_mailbox_items",
            "external_channel_invocation_batches_input_buffer_id_fkey",
        ),
        (
            "mailbox_items",
            "ck_mailbox_items_requested_profile",
            "ck_input_buffers_requested_profile",
        ),
        (
            "mailbox_items",
            "ck_mailbox_items_sender_user_kind",
            "ck_input_buffers_sender_user_kind",
        ),
    ):
        _rename_constraint_if_exists(table, old, new)
    _rename_if_exists(
        "agent_runs", "parent_result_mailbox_item_id", "parent_result_input_buffer_id"
    )
    _rename_if_exists("action_executions", "mailbox_item_id", "input_buffer_id")
    _rename_if_exists(
        "external_channel_invocation_batches", "mailbox_item_id", "input_buffer_id"
    )
    op.execute(
        sa.text(
            "ALTER TYPE IF EXISTS mailbox_item_scheduling_mode "
            "RENAME TO input_buffer_scheduling_mode"
        )
    )
    op.execute(
        sa.text("ALTER TYPE IF EXISTS mailbox_item_kind RENAME TO input_buffer_kind")
    )
    op.execute(sa.text("ALTER TABLE IF EXISTS mailbox_items RENAME TO input_buffers"))
