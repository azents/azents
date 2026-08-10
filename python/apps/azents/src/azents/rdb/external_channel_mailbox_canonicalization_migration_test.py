"""Migration coverage for canonical External Channel mailbox messages."""

import json
from collections.abc import Generator
from contextlib import contextmanager
from typing import cast

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "d0c984babbb1"
_CANONICAL_REVISION = "a9d8b3e5803c"
_SESSION_ID = "session-canonical-mailbox"


@contextmanager
def _migration_database() -> Generator[tuple[AlembicConfig, sa.Engine]]:
    """Create an isolated PostgreSQL database for migration verification."""
    with PostgresContainer("postgres:17", driver="psycopg") as postgres:
        url = postgres.get_connection_url()
        config = AlembicConfig(PROJECT_ROOT / "db-schemas" / "rdb" / "alembic.ini")
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        engine = sa.create_engine(url)
        try:
            yield config, engine
        finally:
            engine.dispose()


def _seed_session(connection: sa.Connection) -> None:
    """Seed the minimum Workspace, Agent, and Session graph."""
    connection.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES (
                'ws-canonical-mailbox',
                'Canonical mailbox migration',
                'canonical-mailbox-migration'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agents (
                id, workspace_id, name, model_selection, lightweight_model_selection,
                selectable_model_options, main_model_label, lightweight_model_label
            )
            VALUES (
                'agent-canonical-mailbox',
                'ws-canonical-mailbox',
                'Canonical mailbox Agent',
                '{}'::jsonb,
                '{}'::jsonb,
                '[{"label":"default","model_selection":{}}]'::jsonb,
                'default',
                'default'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_sessions (
                id, workspace_id, agent_id, handle, status, start_reason, session_kind,
                product_mode
            )
            VALUES (
                :session_id,
                'ws-canonical-mailbox',
                'agent-canonical-mailbox',
                'canonical-mailbox-session',
                'active',
                'initial',
                'root',
                'team'
            )
            """
        ),
        {"session_id": _SESSION_ID},
    )


def _external_message(
    *,
    item_key: str,
    provider_message_key: str,
    authorization: str,
    body: str,
) -> dict[str, object]:
    """Build one representative legacy External Channel mailbox item."""
    return {
        "item_key": item_key,
        "presentation_kind": "external_channel_message",
        "content": body,
        "metadata": {
            "external_channel_message": {
                "provider": "slack",
                "provider_tenant_id": "tenant-migration",
                "resource_id": "resource-migration",
                "resource_label": "C-MIGRATION",
                "resource_type": "thread",
                "binding_id": "binding-migration",
                "invocation_batch_id": "invocation-migration",
                "external_message_id": provider_message_key,
                "projection_root_id": f"projection:{provider_message_key}",
                "provider_message_key": provider_message_key,
                "provider_position": provider_message_key,
                "principal_id": None,
                "provider_user_id": "U-MIGRATION",
                "sender_display_name": "Migration User",
                "author_type": "human",
                "authorization": authorization,
                "body": body,
                "attachment_metadata": {"files": [{"name": "evidence.txt"}]},
                "reference_mappings": {"users": {"U-MIGRATION": "Migration User"}},
                "provider_created_at": "2026-08-10T00:00:00+00:00",
                "provider_updated_at": None,
                "original_url": "https://example.slack.com/archives/C-MIGRATION",
                "truncated_context_message_count": 0,
                "truncated_context_size": 0,
            }
        },
    }


def _seed_legacy_rows(connection: sa.Connection) -> None:
    """Seed ordinary, batched External Channel, and durable Event rows."""
    legacy_payload = {
        "type": "external_channel_invocation",
        "initial_title_eligible": True,
        "items": [
            {
                "item_key": "external_channel:0",
                "presentation_kind": "system_reminder",
                "content": "Earlier provider context was omitted.",
                "metadata": {},
            },
            _external_message(
                item_key="external_channel:1",
                provider_message_key="provider-context",
                authorization="context_only",
                body="Context retained through migration.",
            ),
            _external_message(
                item_key="external_channel:2",
                provider_message_key="provider-trigger",
                authorization="authorized_invocation",
                body="Trigger retained through migration.",
            ),
        ],
    }
    connection.execute(
        sa.text(
            """
            INSERT INTO mailbox_items (
                id, session_id, kind, scheduling_mode,
                requested_model_target_label, requested_reasoning_effort,
                sender_user_id, idempotency_key, payload, created_at
            )
            VALUES
                (
                    'mailbox-ordinary-before',
                    :session_id,
                    'goal_continuation',
                    'queue_only',
                    NULL,
                    NULL,
                    NULL,
                    'ordinary-before',
                    '{"type":"goal_continuation","items":[]}'::jsonb,
                    '2026-08-10T00:00:00+00:00'
                ),
                (
                    'mailbox-external-before',
                    :session_id,
                    'external_channel_invocation',
                    'wake_session',
                    'default',
                    NULL,
                    NULL,
                    'legacy-invocation-key',
                    CAST(:payload AS jsonb),
                    '2026-08-10T00:00:01+00:00'
                )
            """
        ),
        {
            "session_id": _SESSION_ID,
            "payload": json.dumps(legacy_payload),
        },
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO events (
                id, session_id, kind, payload, model_order
            )
            VALUES (
                'event-external-before',
                :session_id,
                'external_channel_message',
                CAST(:payload AS jsonb),
                1
            )
            """
        ),
        {
            "session_id": _SESSION_ID,
            "payload": json.dumps(
                {
                    "provider": "slack",
                    "authorization": "authorized_invocation",
                    "body": "Durable Event content is preserved.",
                    "attachment_metadata": {"files": [{"name": "event.txt"}]},
                }
            ),
        },
    )


def test_canonicalization_splits_mailbox_rows_and_preserves_event_content(
    check_docker_availability: None,
) -> None:
    """Split one legacy batch without losing FIFO, payload, or Event content."""
    del check_docker_availability
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_session(connection)
            _seed_legacy_rows(connection)

        alembic_command.upgrade(config, _CANONICAL_REVISION)
        with engine.connect() as connection:
            rows = (
                connection.execute(
                    sa.text(
                        """
                        SELECT
                            id,
                            kind::text AS kind,
                            idempotency_key,
                            order_group,
                            order_sequence,
                            payload
                        FROM mailbox_items
                        ORDER BY order_group, order_sequence, id
                        """
                    )
                )
                .mappings()
                .all()
            )
            ordinary = next(
                row for row in rows if row["id"] == "mailbox-ordinary-before"
            )
            external = [
                row for row in rows if row["order_group"] == "mailbox-external-before"
            ]
            assert ordinary["order_group"] == ordinary["id"]
            assert ordinary["order_sequence"] == 0
            assert [row["order_sequence"] for row in external] == [0, 1]
            assert external[0]["id"] == "mailbox-external-before"
            assert all(row["kind"] == "external_channel_message" for row in external)
            assert len({row["idempotency_key"] for row in external}) == 2

            context_payload = external[0]["payload"]
            invocation_payload = external[1]["payload"]
            assert context_payload["context_omitted"] is True
            assert context_payload["initial_title_eligible"] is False
            assert invocation_payload["context_omitted"] is False
            assert invocation_payload["initial_title_eligible"] is True
            assert all(len(row["payload"]["items"]) == 1 for row in external)
            context_message = context_payload["items"][0]
            invocation_message = invocation_payload["items"][0]
            assert context_message["item_key"] == "external_channel_message:0"
            assert invocation_message["item_key"] == "external_channel_message:0"
            context_metadata = context_message["metadata"]["external_channel_message"]
            invocation_metadata = invocation_message["metadata"][
                "external_channel_message"
            ]
            assert context_metadata["prompt_role"] == "context"
            assert invocation_metadata["prompt_role"] == "invocation"
            assert "authorization" not in context_metadata
            assert "authorization" not in invocation_metadata
            assert context_metadata["body"] == "Context retained through migration."
            assert invocation_metadata["attachment_metadata"] == {
                "files": [{"name": "evidence.txt"}]
            }

            event_payload = connection.scalar(
                sa.text(
                    """
                    SELECT payload
                    FROM events
                    WHERE id = 'event-external-before'
                    """
                )
            )
            assert event_payload["prompt_role"] == "invocation"
            assert "authorization" not in event_payload
            assert event_payload["body"] == "Durable Event content is preserved."
            assert event_payload["attachment_metadata"] == {
                "files": [{"name": "event.txt"}]
            }

        with pytest.raises(
            RuntimeError,
            match="canonical External Channel mailbox data is unsupported",
        ):
            alembic_command.downgrade(config, _PARENT_REVISION)

        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    DELETE FROM mailbox_items
                    WHERE kind::text = 'external_channel_message'
                    """
                )
            )
        alembic_command.downgrade(config, _PARENT_REVISION)
        with engine.connect() as connection:
            event_payload = connection.scalar(
                sa.text(
                    """
                    SELECT payload
                    FROM events
                    WHERE id = 'event-external-before'
                    """
                )
            )
            assert event_payload["authorization"] == "authorized_invocation"
            assert "prompt_role" not in event_payload
        assert {
            column["name"] for column in sa.inspect(engine).get_columns("mailbox_items")
        }.isdisjoint({"order_group", "order_sequence"})


def test_canonicalization_rejects_malformed_legacy_mailbox_payload(
    check_docker_availability: None,
) -> None:
    """Fail closed before schema or payload changes when legacy input is malformed."""
    del check_docker_availability
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_session(connection)
            malformed = {
                "type": "external_channel_invocation",
                "items": [
                    _external_message(
                        item_key="external_channel:0",
                        provider_message_key="provider-malformed",
                        authorization="context_only",
                        body="Malformed legacy payload.",
                    )
                ],
            }
            message = malformed["items"][0]
            assert isinstance(message, dict)
            metadata = cast(dict[str, object], message["metadata"])
            assert isinstance(metadata, dict)
            external_metadata = cast(
                dict[str, object],
                metadata["external_channel_message"],
            )
            assert isinstance(external_metadata, dict)
            del external_metadata["authorization"]
            connection.execute(
                sa.text(
                    """
                    INSERT INTO mailbox_items (
                        id, session_id, kind, scheduling_mode,
                        requested_model_target_label, requested_reasoning_effort,
                        sender_user_id, idempotency_key, payload
                    )
                    VALUES (
                        'mailbox-malformed-before',
                        :session_id,
                        'external_channel_invocation',
                        'wake_session',
                        NULL,
                        NULL,
                        NULL,
                        'malformed-before',
                        CAST(:payload AS jsonb)
                    )
                    """
                ),
                {
                    "session_id": _SESSION_ID,
                    "payload": json.dumps(malformed),
                },
            )

        with pytest.raises(
            RuntimeError,
            match="Legacy External Channel mailbox payload is malformed",
        ):
            alembic_command.upgrade(config, _CANONICAL_REVISION)

        assert {
            column["name"] for column in sa.inspect(engine).get_columns("mailbox_items")
        }.isdisjoint({"order_group", "order_sequence"})
        with engine.connect() as connection:
            payload = connection.scalar(
                sa.text(
                    """
                    SELECT payload
                    FROM mailbox_items
                    WHERE id = 'mailbox-malformed-before'
                    """
                )
            )
            assert payload["type"] == "external_channel_invocation"
