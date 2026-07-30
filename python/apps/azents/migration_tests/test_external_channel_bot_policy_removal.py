"""Migration tests for External Channel bot-policy removal."""

import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

_PARENT_REVISION = "f1a13c6dc46d"
_REVISION = "d307822ec9d7"


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    """Return the reflected column names for one table."""
    return {column["name"] for column in inspector.get_columns(table)}


def _seed_parent_graph(connection: sa.Connection) -> None:
    """Seed pending sources with retained and unretained provider content."""
    connection.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    connection.execute(
        sa.text(
            """
            INSERT INTO users (id, primary_email_id)
            VALUES ('bot-policy-user', 'bot-policy-email')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO user_emails (id, user_id, email, verified_at)
            VALUES (
                'bot-policy-email',
                'bot-policy-user',
                'bot-policy-migration@example.com',
                now()
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES ('bot-policy-workspace', 'Bot Policy', 'bot-policy-migration')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO workspace_users (
                id, workspace_id, user_id, name, role
            )
            VALUES (
                'bot-policy-workspace-user',
                'bot-policy-workspace',
                'bot-policy-user',
                'Bot Policy User',
                'owner'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agents (
                id, workspace_id, name, model_selection,
                lightweight_model_selection, selectable_model_options,
                main_model_label, lightweight_model_label
            )
            VALUES (
                'bot-policy-agent',
                'bot-policy-workspace',
                'Bot Policy Agent',
                '{}'::jsonb,
                '{}'::jsonb,
                '[
                    {"label": "bot-policy-main", "model_selection": {}},
                    {"label": "bot-policy-light", "model_selection": {}}
                ]'::jsonb,
                'bot-policy-main',
                'bot-policy-light'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_sessions (
                id, workspace_id, agent_id, handle, status, start_reason,
                session_kind
            )
            VALUES (
                'bot-policy-session',
                'bot-policy-workspace',
                'bot-policy-agent',
                'bot-policy-session',
                'active',
                'external_channel',
                'root'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_connections (
                id, workspace_id, provider, transport, ingress_profile, status,
                app_mode, provider_app_id, provider_tenant_id
            )
            VALUES (
                'bot-policy-connection',
                'bot-policy-workspace',
                'slack',
                'http',
                'slack_http',
                'active',
                'single',
                'bot-policy-app',
                'bot-policy-tenant'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_agent_routes (
                id, connection_id, agent_id, agent_id_snapshot, route_mode,
                connection_app_mode, catalog_status, allow_bot_messages
            )
            VALUES (
                'bot-policy-route',
                'bot-policy-connection',
                'bot-policy-agent',
                'bot-policy-agent',
                'dedicated',
                'single',
                'available',
                true
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_principals (
                id, provider, provider_tenant_id, provider_user_id, author_type
            )
            VALUES (
                'bot-policy-principal',
                'slack',
                'bot-policy-tenant',
                'bot-policy-provider-user',
                'human'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_resources (
                id, connection_id, resource_type, provider_resource_key, status
            )
            VALUES
                (
                    'bot-policy-retained-resource',
                    'bot-policy-connection',
                    'thread',
                    'slack:retained',
                    'active'
                ),
                (
                    'bot-policy-scrubbed-resource',
                    'bot-policy-connection',
                    'thread',
                    'slack:scrubbed',
                    'active'
                )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_conversation_positions (
                id, connection_id, scope_kind, provider_channel_id,
                provider_thread_key, read_through_position
            )
            VALUES
                (
                    'bot-policy-retained-position',
                    'bot-policy-connection',
                    'thread',
                    'retained-channel',
                    'retained-thread',
                    NULL
                ),
                (
                    'bot-policy-scrubbed-position',
                    'bot-policy-connection',
                    'thread',
                    'scrubbed-channel',
                    'scrubbed-thread',
                    NULL
                )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_messages (
                id, resource_id, provider_message_key, provider_position,
                lifecycle, author_type, principal_id, original_url, pending_size
            )
            VALUES
                (
                    'bot-policy-retained-message',
                    'bot-policy-retained-resource',
                    'slack:retained-message',
                    '1.000001',
                    'current',
                    'human',
                    'bot-policy-principal',
                    'https://provider.invalid/retained',
                    101
                ),
                (
                    'bot-policy-scrubbed-message',
                    'bot-policy-scrubbed-resource',
                    'slack:scrubbed-message',
                    '2.000001',
                    'current',
                    'human',
                    'bot-policy-principal',
                    'https://provider.invalid/scrubbed',
                    202
                )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_message_revisions (
                id, message_id, revision_key, revision_kind, normalized_body,
                attachment_metadata, reference_mappings
            )
            VALUES
                (
                    'bot-policy-retained-revision',
                    'bot-policy-retained-message',
                    'v1',
                    'original',
                    'retained body',
                    '{"attachment": "retained"}'::jsonb,
                    '{"reference": "retained"}'::jsonb
                ),
                (
                    'bot-policy-retained-current',
                    'bot-policy-retained-message',
                    'v2',
                    'edit',
                    'unaccepted retained edit',
                    '{"attachment": "unaccepted"}'::jsonb,
                    '{"reference": "unaccepted"}'::jsonb
                ),
                (
                    'bot-policy-scrubbed-revision',
                    'bot-policy-scrubbed-message',
                    'v1',
                    'original',
                    'scrubbed body',
                    '{"attachment": "scrubbed"}'::jsonb,
                    '{"reference": "scrubbed"}'::jsonb
                )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE external_channel_messages
            SET current_revision_id = CASE id
                WHEN 'bot-policy-retained-message'
                    THEN 'bot-policy-retained-current'
                WHEN 'bot-policy-scrubbed-message'
                    THEN 'bot-policy-scrubbed-revision'
            END
            WHERE id IN (
                'bot-policy-retained-message',
                'bot-policy-scrubbed-message'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_bindings (
                id, resource_id, route_id, agent_session_id, status
            )
            VALUES (
                'bot-policy-binding',
                'bot-policy-retained-resource',
                'bot-policy-route',
                'bot-policy-session',
                'active'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_invocation_batches (
                id, binding_id, trigger_message_id, first_provider_position,
                last_provider_position, connection_id,
                conversation_position_id, trigger_position
            )
            VALUES (
                'bot-policy-batch',
                'bot-policy-binding',
                'bot-policy-retained-message',
                '1.000001',
                '1.000001',
                'bot-policy-connection',
                'bot-policy-retained-position',
                '1.000001'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_invocation_batch_items (
                id, batch_id, message_revision_id, sequence, provider_position
            )
            VALUES (
                'bot-policy-batch-item',
                'bot-policy-batch',
                'bot-policy-retained-revision',
                0,
                '1.000001'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_access_requests (
                id, route_id, resource_id, source_message_id, principal_id,
                status, decision_policy_snapshot, expires_at, connection_id,
                conversation_position_id, trigger_position
            )
            VALUES (
                'bot-policy-access-request',
                'bot-policy-route',
                'bot-policy-retained-resource',
                'bot-policy-retained-message',
                'bot-policy-principal',
                'pending',
                '{}'::jsonb,
                now() + interval '1 hour',
                'bot-policy-connection',
                'bot-policy-retained-position',
                '1.000001'
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO external_channel_conversation_admissions (
                id, connection_id, resource_id, source_message_id, origin,
                status, expires_at, initiating_principal_id,
                conversation_position_id, trigger_position
            )
            VALUES (
                'bot-policy-admission',
                'bot-policy-connection',
                'bot-policy-scrubbed-resource',
                'bot-policy-scrubbed-message',
                'mention_selector',
                'pending_selection',
                now() + interval '1 hour',
                'bot-policy-principal',
                'bot-policy-scrubbed-position',
                '2.000001'
            )
            """
        )
    )


def _message_state(
    connection: sa.Connection,
    *,
    message_id: str,
) -> tuple[str | None, str | None, int]:
    """Return retained content pointers for one message."""
    row = connection.execute(
        sa.text(
            """
            SELECT current_revision_id, original_url, pending_size
            FROM external_channel_messages
            WHERE id = :message_id
            """
        ),
        {"message_id": message_id},
    ).one()
    return row.current_revision_id, row.original_url, row.pending_size


def test_bot_policy_removal_scrubs_only_unaccepted_pending_content(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Archive route policy and scrub only unaccepted pending provider content."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_parent_graph(connection)

    alembic_runner.migrate_up_to(_REVISION)

    inspector = sa.inspect(alembic_engine)
    assert "allow_bot_messages" not in _column_names(
        inspector,
        "external_channel_agent_routes",
    )
    assert (
        "external_channel_agent_route_bot_policy_archive" in inspector.get_table_names()
    )
    with alembic_engine.connect() as connection:
        assert connection.execute(
            sa.text(
                """
                SELECT allow_bot_messages
                FROM external_channel_agent_route_bot_policy_archive
                WHERE route_id = 'bot-policy-route'
                """
            )
        ).scalar_one()
        assert _message_state(
            connection,
            message_id="bot-policy-scrubbed-message",
        ) == (None, None, 0)
        assert (
            connection.execute(
                sa.text(
                    """
                    SELECT count(*)
                    FROM external_channel_message_revisions
                    WHERE id = 'bot-policy-scrubbed-revision'
                    """
                )
            ).scalar_one()
            == 0
        )
        assert _message_state(
            connection,
            message_id="bot-policy-retained-message",
        ) == (
            None,
            "https://provider.invalid/retained",
            101,
        )
        assert (
            connection.execute(
                sa.text(
                    """
                    SELECT normalized_body
                    FROM external_channel_message_revisions
                    WHERE id = 'bot-policy-retained-revision'
                    """
                )
            ).scalar_one()
            == "retained body"
        )
        assert (
            connection.execute(
                sa.text(
                    """
                    SELECT count(*)
                    FROM external_channel_message_revisions
                    WHERE id = 'bot-policy-retained-current'
                    """
                )
            ).scalar_one()
            == 0
        )

    alembic_runner.migrate_down_to(_PARENT_REVISION)

    inspector = sa.inspect(alembic_engine)
    assert "allow_bot_messages" in _column_names(
        inspector,
        "external_channel_agent_routes",
    )
    assert (
        "external_channel_agent_route_bot_policy_archive"
        not in inspector.get_table_names()
    )
    with alembic_engine.connect() as connection:
        assert connection.execute(
            sa.text(
                """
                SELECT allow_bot_messages
                FROM external_channel_agent_routes
                WHERE id = 'bot-policy-route'
                """
            )
        ).scalar_one()
        assert _message_state(
            connection,
            message_id="bot-policy-scrubbed-message",
        ) == (None, None, 0)
        assert _message_state(
            connection,
            message_id="bot-policy-retained-message",
        ) == (
            None,
            "https://provider.invalid/retained",
            101,
        )
