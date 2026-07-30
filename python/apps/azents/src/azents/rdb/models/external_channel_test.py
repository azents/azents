"""Installed-schema tests for External Channel persistence."""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine.interfaces import ReflectedForeignKeyConstraint
from sqlalchemy.engine.reflection import Inspector
from testcontainers.postgres import PostgresContainer

from azents.rdb.models.base import RDBModel
from azents.rdb.models.external_channel import (
    RDBExternalChannelAccessGrant,
    RDBExternalChannelAccessRequest,
    RDBExternalChannelAction,
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelBlock,
    RDBExternalChannelChannelDefault,
    RDBExternalChannelConnection,
    RDBExternalChannelConversationAdmission,
    RDBExternalChannelDeliveryAttempt,
    RDBExternalChannelInteraction,
    RDBExternalChannelInvocationBatch,
    RDBExternalChannelInvocationBatchItem,
    RDBExternalChannelMessage,
    RDBExternalChannelMessageRevision,
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


def _foreign_key_by_columns(
    foreign_keys: Sequence[ReflectedForeignKeyConstraint],
    constrained_columns: Sequence[str],
) -> ReflectedForeignKeyConstraint:
    """Return one installed foreign key by its constrained columns."""
    return next(
        foreign_key
        for foreign_key in foreign_keys
        if foreign_key["constrained_columns"] == list(constrained_columns)
    )


def _columns_by_name(
    inspector: Inspector,
    table_name: str,
) -> dict[str, Mapping[str, Any]]:
    """Return installed column reflection indexed by name."""
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def _assert_server_default(column: Mapping[str, Any], expected: str) -> None:
    """Assert a reflected PostgreSQL server default contains one stable token."""
    default = column["default"]
    assert default is not None
    assert expected in str(default).lower()


def test_current_revision_foreign_key_is_deferred_no_action() -> None:
    """Allow a message and its cascaded revisions to disappear atomically."""
    foreign_key = RDBExternalChannelMessage.FK_CURRENT_REVISION

    assert foreign_key.ondelete is None
    assert foreign_key.deferrable is True
    assert foreign_key.initially == "DEFERRED"


def test_external_channel_explicit_identifiers_fit_postgresql_limit() -> None:
    """Keep explicit schema identifiers within PostgreSQL's 63-byte limit."""
    identifiers: list[str] = []
    for table in RDBModel.metadata.tables.values():
        if not table.name.startswith("external_channel_"):
            continue
        identifiers.append(table.name)
        for constraint in table.constraints:
            if constraint.name is not None:
                identifiers.append(str(constraint.name))
        for index in table.indexes:
            if index.name is not None:
                identifiers.append(str(index.name))

    assert identifiers
    assert all(len(identifier.encode()) <= 63 for identifier in identifiers)


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
        assert (
            "external_channel_agent_routes",
            "agent_id",
            "agents",
            "SET NULL",
        ) in restrictive_roots

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
                _foreign_key_by_columns(
                    batch_item_foreign_keys,
                    ["message_revision_id"],
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
            RDBExternalChannelInteraction,
            RDBExternalChannelConversationAdmission,
            RDBExternalChannelChannelDefault,
            RDBExternalChannelPrincipal,
            RDBExternalChannelMessage,
            RDBExternalChannelMessageRevision,
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


def test_external_channel_installed_schema_excludes_retired_processing_state(
    latest_db_schema: None,
    postgres_container: PostgresContainer,
) -> None:
    """Verify the installed schema contains only retained canonical authorities."""
    engine = create_engine(postgres_container.get_connection_url())
    try:
        inspector = inspect(engine)
        assert {
            "external_channel_events",
            "external_channel_pending_contexts",
        }.isdisjoint(inspector.get_table_names())
        retired_columns = {
            "external_channel_resources": {
                "hydration_status",
                "hydration_cursor",
                "hydration_high_watermark_position",
                "reconciliation_boundary_received_at",
                "reconciliation_boundary_event_id",
                "hydration_error_kind",
                "hydration_error_summary",
                "hydration_started_at",
                "hydration_completed_at",
            },
            "external_channel_bindings": {
                "activation_status",
                "activation_trigger_message_id",
                "activated_at",
                "activation_wake_claimed_at",
                "projected_through_position",
                "truncated_message_count",
                "truncated_size",
            },
            "external_channel_invocation_batches": {
                "truncation_message_count",
                "truncation_size",
            },
            "external_channel_message_revisions": {"source_event_id"},
        }
        for table_name, column_names in retired_columns.items():
            assert column_names.isdisjoint(_columns_by_name(inspector, table_name))

        conversation_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints(
                "external_channel_conversation_admissions"
            )
        }
        access_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints(
                "external_channel_access_requests"
            )
        }
        assert (
            "ck_external_channel_conversation_admissions_open_boundary"
            in conversation_checks
        )
        assert "ck_external_channel_access_requests_pending_boundary" in access_checks

        with engine.connect() as connection:
            retired_enums = set(
                connection.scalars(
                    text(
                        """
                        SELECT typname
                        FROM pg_type
                        WHERE typtype = 'e'
                          AND typname IN (
                              'external_channel_event_eligibility_state',
                              'external_channel_event_status',
                              'external_channel_hydration_status',
                              'external_channel_binding_activation_status'
                          )
                        """
                    )
                )
            )
        assert retired_enums == set()
    finally:
        engine.dispose()


def test_external_channel_app_mode_installed_schema_contract(
    latest_db_schema: None,
    postgres_container: PostgresContainer,
) -> None:
    """Verify every Phase 1 named PostgreSQL constraint matches ORM metadata."""
    engine = create_engine(postgres_container.get_connection_url())
    try:
        inspector = inspect(engine)
        with engine.connect() as connection:
            enum_values = {
                row["type_name"]: tuple(row["values"])
                for row in connection.execute(
                    text(
                        """
                        SELECT pg_type.typname AS type_name,
                               array_agg(
                                   pg_enum.enumlabel
                                   ORDER BY pg_enum.enumsortorder
                               )
                                   AS values
                        FROM pg_type
                        JOIN pg_enum ON pg_enum.enumtypid = pg_type.oid
                        WHERE pg_type.typname IN (
                            'external_channel_app_mode',
                            'external_channel_route_catalog_status',
                            'external_channel_interaction_type',
                            'external_channel_interaction_status',
                            'external_channel_conversation_admission_origin',
                            'external_channel_conversation_admission_status',
                            'external_channel_channel_default_status'
                        )
                        GROUP BY pg_type.typname
                        """
                    )
                ).mappings()
            }
            index_definitions = {
                row["index_name"]: row["definition"]
                for row in connection.execute(
                    text(
                        """
                        SELECT indexrelid::regclass::text AS index_name,
                               pg_get_indexdef(indexrelid) AS definition
                        FROM pg_index
                        WHERE indrelid IN (
                            'external_channel_agent_routes'::regclass,
                            'external_channel_conversation_admissions'::regclass,
                            'external_channel_channel_defaults'::regclass,
                            'external_channel_bindings'::regclass
                        )
                        """
                    )
                ).mappings()
            }
            trigger = (
                connection.execute(
                    text(
                        """
                    SELECT trigger_name, action_statement
                    FROM information_schema.triggers
                    WHERE event_object_table = 'external_channel_connections'
                      AND trigger_name =
                          'external_channel_connections_app_mode_immutable'
                    """
                    )
                )
                .mappings()
                .one()
            )
            function_exists = connection.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_proc
                        WHERE proname =
                            'prevent_external_channel_connection_app_mode_update'
                    )
                    """
                )
            )

        assert enum_values == {
            "external_channel_app_mode": ("single", "multi"),
            "external_channel_route_catalog_status": ("available", "removed"),
            "external_channel_interaction_type": (
                "shortcut",
                "block_action",
                "options",
                "view_submission",
                "management_action",
            ),
            "external_channel_interaction_status": (
                "accepted",
                "processing",
                "completed",
                "expired",
                "rejected",
                "failed",
            ),
            "external_channel_conversation_admission_origin": (
                "single_route",
                "channel_default",
                "shortcut",
                "mention_selector",
            ),
            "external_channel_conversation_admission_status": (
                "pending_selection",
                "selected",
                "awaiting_access",
                "bound",
                "expired",
                "rejected",
            ),
            "external_channel_channel_default_status": ("active", "invalidated"),
        }
        assert (
            trigger["trigger_name"] == "external_channel_connections_app_mode_immutable"
        )
        assert (
            "prevent_external_channel_connection_app_mode_update"
            in trigger["action_statement"]
        )
        assert function_exists is True

        connection_unique_constraints = {
            constraint["name"]: tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(
                "external_channel_connections"
            )
        }
        route_unique_constraints = {
            constraint["name"]: tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(
                "external_channel_agent_routes"
            )
        }
        resource_unique_constraints = {
            constraint["name"]: tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(
                "external_channel_resources"
            )
        }
        message_unique_constraints = {
            constraint["name"]: tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(
                "external_channel_messages"
            )
        }
        interaction_unique_constraints = {
            constraint["name"]: tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(
                "external_channel_interactions"
            )
        }
        assert connection_unique_constraints[
            "uq_external_channel_connections_id_app_mode"
        ] == ("id", "app_mode")
        assert route_unique_constraints[
            "uq_external_channel_agent_routes_connection_agent"
        ] == ("connection_id", "agent_id_snapshot")
        assert route_unique_constraints[
            "uq_external_channel_agent_routes_connection_id_id"
        ] == ("connection_id", "id")
        assert resource_unique_constraints[
            "uq_external_channel_resources_connection_id_id"
        ] == ("connection_id", "id")
        assert message_unique_constraints[
            "uq_external_channel_messages_resource_id_id"
        ] == ("resource_id", "id")
        assert interaction_unique_constraints[
            "uq_external_channel_interactions_connection_provider_key"
        ] == ("connection_id", "provider_interaction_key")
        assert interaction_unique_constraints[
            "uq_external_channel_interactions_connection_id_id"
        ] == ("connection_id", "id")

        route_foreign_keys = inspector.get_foreign_keys("external_channel_agent_routes")
        route_mode_shadow_foreign_key = _foreign_key(
            route_foreign_keys,
            "fk_external_channel_agent_routes_connection_app_mode",
        )
        assert route_mode_shadow_foreign_key["constrained_columns"] == [
            "connection_id",
            "connection_app_mode",
        ]
        assert route_mode_shadow_foreign_key["referred_columns"] == ["id", "app_mode"]
        assert _foreign_key_options(route_mode_shadow_foreign_key)["ondelete"] == (
            "RESTRICT"
        )
        route_catalog_removed_by_foreign_key = _foreign_key(
            route_foreign_keys,
            "external_channel_agent_routes_catalog_removed_by_user_id_fkey",
        )
        assert route_catalog_removed_by_foreign_key["constrained_columns"] == [
            "catalog_removed_by_user_id"
        ]
        assert route_catalog_removed_by_foreign_key["referred_columns"] == ["id"]
        assert (
            _foreign_key_options(route_catalog_removed_by_foreign_key)["ondelete"]
            == "RESTRICT"
        )

        admissions_foreign_keys = inspector.get_foreign_keys(
            "external_channel_conversation_admissions"
        )
        expected_admission_foreign_keys = {
            "fk_external_channel_conv_admissions_connection_resource": (
                ["connection_id", "resource_id"],
                ["connection_id", "id"],
            ),
            "fk_external_channel_conv_admissions_resource_source_message": (
                ["resource_id", "source_message_id"],
                ["resource_id", "id"],
            ),
            "fk_external_channel_conv_admissions_connection_selected_route": (
                ["connection_id", "selected_route_id"],
                ["connection_id", "id"],
            ),
            "fk_external_channel_conv_admissions_connection_interaction": (
                ["connection_id", "interaction_id"],
                ["connection_id", "id"],
            ),
        }
        for name, (constrained, referred) in expected_admission_foreign_keys.items():
            foreign_key = _foreign_key(admissions_foreign_keys, name)
            assert foreign_key["constrained_columns"] == constrained
            assert foreign_key["referred_columns"] == referred
            assert _foreign_key_options(foreign_key)["ondelete"] == "RESTRICT"

        defaults_foreign_key = _foreign_key(
            inspector.get_foreign_keys("external_channel_channel_defaults"),
            "fk_external_channel_channel_defaults_connection_route",
        )
        assert defaults_foreign_key["constrained_columns"] == [
            "connection_id",
            "route_id",
        ]
        assert defaults_foreign_key["referred_columns"] == ["connection_id", "id"]
        assert _foreign_key_options(defaults_foreign_key)["ondelete"] == "RESTRICT"

        installed_indexes = {
            index["name"]: tuple(index["column_names"])
            for table_name in (
                "external_channel_agent_routes",
                "external_channel_interactions",
                "external_channel_conversation_admissions",
                "external_channel_channel_defaults",
                "external_channel_bindings",
            )
            for index in inspector.get_indexes(table_name)
        }
        assert {
            "uq_external_channel_agent_routes_single_connection": ("connection_id",),
            "ix_external_channel_interactions_expires_at": ("expires_at",),
            "ix_external_channel_conversation_admissions_connection_status": (
                "connection_id",
                "status",
            ),
            "ix_external_channel_conversation_admissions_expires_at": ("expires_at",),
            "uq_external_channel_conversation_admissions_open_resource": (
                "resource_id",
            ),
            "ix_external_channel_channel_defaults_route_id_status": (
                "route_id",
                "status",
            ),
            "uq_external_channel_channel_defaults_active_connection_channel": (
                "connection_id",
                "provider_channel_id",
            ),
            "uq_external_channel_bindings_active_resource": ("resource_id",),
        }.items() <= installed_indexes.items()
        assert (
            "WHERE (connection_app_mode = 'single'::external_channel_app_mode)"
            in (index_definitions["uq_external_channel_agent_routes_single_connection"])
        )
        assert (
            "WHERE (status = ANY (ARRAY['pending_selection'::"
            "external_channel_conversation_admission_status, 'selected'::"
            "external_channel_conversation_admission_status, 'awaiting_access'::"
            "external_channel_conversation_admission_status]))"
            in index_definitions[
                "uq_external_channel_conversation_admissions_open_resource"
            ]
        )
        assert (
            "WHERE (status = 'active'::external_channel_channel_default_status)"
            in (
                index_definitions[
                    "uq_external_channel_channel_defaults_active_connection_channel"
                ]
            )
        )
        assert (
            "WHERE (status = 'active'::external_channel_binding_status)"
            in (index_definitions["uq_external_channel_bindings_active_resource"])
        )

        connection_columns = _columns_by_name(inspector, "external_channel_connections")
        route_columns = _columns_by_name(inspector, "external_channel_agent_routes")
        interaction_columns = _columns_by_name(
            inspector, "external_channel_interactions"
        )
        admission_columns = _columns_by_name(
            inspector, "external_channel_conversation_admissions"
        )
        default_columns = _columns_by_name(
            inspector, "external_channel_channel_defaults"
        )
        assert connection_columns["app_mode"]["nullable"] is False
        _assert_server_default(connection_columns["app_mode"], "single")
        assert route_columns["connection_app_mode"]["nullable"] is False
        _assert_server_default(route_columns["connection_app_mode"], "single")
        assert route_columns["catalog_status"]["nullable"] is False
        _assert_server_default(route_columns["catalog_status"], "available")
        for column_name in ("catalog_removed_at", "catalog_removed_by_user_id"):
            assert route_columns[column_name]["nullable"] is True
            assert route_columns[column_name]["default"] is None

        for column_name in (
            "id",
            "connection_id",
            "transport",
            "provider_interaction_key",
            "interaction_type",
            "projection",
            "status",
            "expires_at",
            "created_at",
            "updated_at",
        ):
            assert interaction_columns[column_name]["nullable"] is False
        for column_name in (
            "callback_id",
            "action_id",
            "principal_id",
            "resource_correlation_key",
            "error_kind",
            "error_summary",
        ):
            assert interaction_columns[column_name]["nullable"] is True
        _assert_server_default(interaction_columns["status"], "accepted")
        _assert_server_default(interaction_columns["created_at"], "now")
        _assert_server_default(interaction_columns["updated_at"], "now")

        for column_name in (
            "id",
            "connection_id",
            "resource_id",
            "source_message_id",
            "origin",
            "status",
            "expires_at",
            "created_at",
            "updated_at",
        ):
            assert admission_columns[column_name]["nullable"] is False
        for column_name in (
            "initiating_principal_id",
            "selected_route_id",
            "interaction_id",
        ):
            assert admission_columns[column_name]["nullable"] is True
        _assert_server_default(admission_columns["created_at"], "now")
        _assert_server_default(admission_columns["updated_at"], "now")

        for column_name in (
            "id",
            "connection_id",
            "provider_channel_id",
            "route_id",
            "status",
            "configured_by_user_id",
            "created_at",
            "updated_at",
        ):
            assert default_columns[column_name]["nullable"] is False
        for column_name in ("invalidated_at", "invalidation_reason"):
            assert default_columns[column_name]["nullable"] is True
        _assert_server_default(default_columns["status"], "active")
        _assert_server_default(default_columns["created_at"], "now")
        _assert_server_default(default_columns["updated_at"], "now")

        interaction_foreign_keys = inspector.get_foreign_keys(
            "external_channel_interactions"
        )
        for constrained_columns in (("connection_id",), ("principal_id",)):
            assert (
                _foreign_key_options(
                    _foreign_key_by_columns(
                        interaction_foreign_keys, constrained_columns
                    )
                )["ondelete"]
                == "RESTRICT"
            )
        for foreign_key in admissions_foreign_keys:
            assert _foreign_key_options(foreign_key)["ondelete"] == "RESTRICT"
        for foreign_key in inspector.get_foreign_keys(
            "external_channel_channel_defaults"
        ):
            assert _foreign_key_options(foreign_key)["ondelete"] == "RESTRICT"
    finally:
        engine.dispose()
