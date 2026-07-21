"""Installed-schema tests for External Channel persistence."""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine.interfaces import ReflectedForeignKeyConstraint
from testcontainers.postgres import PostgresContainer

from azents.rdb.models.base import RDBModel
from azents.rdb.models.external_channel import (
    RDBExternalChannelAccessGrant,
    RDBExternalChannelAccessRequest,
    RDBExternalChannelAction,
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelBlock,
    RDBExternalChannelConnection,
    RDBExternalChannelDeliveryAttempt,
    RDBExternalChannelEvent,
    RDBExternalChannelInvocationBatch,
    RDBExternalChannelInvocationBatchItem,
    RDBExternalChannelMessage,
    RDBExternalChannelMessageRevision,
    RDBExternalChannelPendingContext,
    RDBExternalChannelPrincipal,
    RDBExternalChannelResource,
    RDBExternalChannelWork,
)


def _foreign_key(
    foreign_keys: Sequence[ReflectedForeignKeyConstraint],
    name: str,
) -> ReflectedForeignKeyConstraint:
    """Return one installed foreign key by its explicit name."""
    return next(
        foreign_key for foreign_key in foreign_keys if foreign_key["name"] == name
    )


def _foreign_key_options(
    foreign_key: ReflectedForeignKeyConstraint,
) -> Mapping[str, Any]:
    """Return installed optional FK options as a mapping."""
    return foreign_key.get("options", {})


def test_current_revision_foreign_key_is_deferred_no_action() -> None:
    """Allow a message and its cascaded revisions to disappear atomically."""
    foreign_key = RDBExternalChannelMessage.FK_CURRENT_REVISION

    assert foreign_key.ondelete is None
    assert foreign_key.deferrable is True
    assert foreign_key.initially == "DEFERRED"


def test_external_channel_installed_schema_preserves_lifecycle_ownership(
    latest_db_schema: None,
    postgres_container: PostgresContainer,
) -> None:
    """Verify restrictive lifecycle roots and intentional pure-child cascades."""
    engine = create_engine(postgres_container.get_connection_url())
    try:
        inspector = inspect(engine)

        with engine.connect() as connection:
            restrictive_roots = {
                (
                    row.table_name,
                    row.column_name,
                    row.referred_table,
                    row.delete_rule,
                )
                for row in connection.execute(
                    text(
                        """
                        SELECT
                            tc.table_name,
                            kcu.column_name,
                            ccu.table_name AS referred_table,
                            rc.delete_rule
                        FROM information_schema.table_constraints AS tc
                        JOIN information_schema.key_column_usage AS kcu
                          ON tc.constraint_catalog = kcu.constraint_catalog
                         AND tc.constraint_schema = kcu.constraint_schema
                         AND tc.constraint_name = kcu.constraint_name
                        JOIN information_schema.referential_constraints AS rc
                          ON tc.constraint_catalog = rc.constraint_catalog
                         AND tc.constraint_schema = rc.constraint_schema
                         AND tc.constraint_name = rc.constraint_name
                        JOIN information_schema.constraint_column_usage AS ccu
                          ON rc.unique_constraint_catalog = ccu.constraint_catalog
                         AND rc.unique_constraint_schema = ccu.constraint_schema
                         AND rc.unique_constraint_name = ccu.constraint_name
                        WHERE tc.constraint_type = 'FOREIGN KEY'
                          AND tc.table_schema = current_schema()
                        """
                    )
                )
            }
        assert {
            (
                "external_channel_bindings",
                "agent_session_id",
                "agent_sessions",
                "RESTRICT",
            ),
            (
                "external_channel_access_requests",
                "agent_session_id",
                "agent_sessions",
                "RESTRICT",
            ),
            (
                "external_channel_access_grants",
                "agent_session_id",
                "agent_sessions",
                "RESTRICT",
            ),
            (
                "external_channel_actions",
                "agent_session_id",
                "agent_sessions",
                "RESTRICT",
            ),
            (
                "external_channel_pending_contexts",
                "route_id",
                "external_channel_agent_routes",
                "RESTRICT",
            ),
            (
                "external_channel_agent_routes",
                "agent_id",
                "agents",
                "RESTRICT",
            ),
            (
                "external_channel_access_grants",
                "agent_id",
                "agents",
                "RESTRICT",
            ),
            (
                "external_channel_blocks",
                "agent_id",
                "agents",
                "RESTRICT",
            ),
        }.issubset(restrictive_roots)

        batch_item_foreign_keys = inspector.get_foreign_keys(
            "external_channel_invocation_batch_items"
        )
        assert (
            _foreign_key_options(
                _foreign_key(
                    batch_item_foreign_keys,
                    "external_channel_invocation_batch_items_batch_id_fkey",
                )
            )["ondelete"]
            == "CASCADE"
        )
        assert (
            _foreign_key_options(
                _foreign_key(
                    batch_item_foreign_keys,
                    "external_channel_invocation_batch_items_message_revision_id_fkey",
                )
            )["ondelete"]
            == "RESTRICT"
        )

        revision_foreign_keys = inspector.get_foreign_keys(
            "external_channel_message_revisions"
        )
        assert (
            _foreign_key_options(
                _foreign_key(
                    revision_foreign_keys,
                    "external_channel_message_revisions_message_id_fkey",
                )
            )["ondelete"]
            == "CASCADE"
        )

        current_revision_foreign_key = _foreign_key(
            inspector.get_foreign_keys("external_channel_messages"),
            "fk_external_channel_messages_current_revision",
        )
        assert current_revision_foreign_key["constrained_columns"] == [
            "id",
            "current_revision_id",
        ]
        assert current_revision_foreign_key["referred_columns"] == [
            "message_id",
            "id",
        ]
        current_revision_options = _foreign_key_options(current_revision_foreign_key)
        assert current_revision_options.get("ondelete") in (
            None,
            "NO ACTION",
        )
        assert current_revision_options["deferrable"] is True
        assert current_revision_options["initially"] == "DEFERRED"
    finally:
        engine.dispose()


def test_external_channel_migration_matches_model_metadata(
    latest_db_schema: None,
    postgres_container: PostgresContainer,
) -> None:
    """Verify the migrated External Channel tables contain every ORM column."""
    engine = create_engine(postgres_container.get_connection_url())
    try:
        inspector = inspect(engine)
        model_tables = (
            RDBExternalChannelConnection,
            RDBExternalChannelAgentRoute,
            RDBExternalChannelResource,
            RDBExternalChannelEvent,
            RDBExternalChannelPrincipal,
            RDBExternalChannelMessage,
            RDBExternalChannelMessageRevision,
            RDBExternalChannelPendingContext,
            RDBExternalChannelBinding,
            RDBExternalChannelInvocationBatch,
            RDBExternalChannelInvocationBatchItem,
            RDBExternalChannelAccessRequest,
            RDBExternalChannelAccessGrant,
            RDBExternalChannelBlock,
            RDBExternalChannelWork,
            RDBExternalChannelAction,
            RDBExternalChannelDeliveryAttempt,
        )
        for model in model_tables:
            table = RDBModel.metadata.tables[model.__tablename__]
            installed_columns = {
                column["name"] for column in inspector.get_columns(table.name)
            }
            assert {column.name for column in table.columns} == installed_columns
    finally:
        engine.dispose()
