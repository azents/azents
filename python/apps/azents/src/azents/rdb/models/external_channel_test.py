"""Installed-schema tests for retained External Channel persistence."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine.reflection import Inspector
from testcontainers.postgres import PostgresContainer

from azents.rdb.models.base import RDBModel
from azents.rdb.models.external_channel import RDBExternalChannelConnection

_RETIRED_TABLES = {
    "external_channel_messages",
    "external_channel_message_revisions",
    "external_channel_invocation_batches",
    "external_channel_invocation_batch_items",
    "external_channel_conversation_admissions",
    "external_channel_resource_provisionings",
}
_RETIRED_ENUMS = {
    "external_channel_conversation_admission_origin",
    "external_channel_conversation_admission_status",
    "external_channel_invocation_wake_dispatch_status",
    "external_channel_message_lifecycle",
    "external_channel_message_revision_kind",
    "external_channel_resource_provisioning_operation",
    "external_channel_resource_provisioning_status",
}


def _columns_by_name(
    inspector: Inspector,
    table_name: str,
) -> dict[str, Mapping[str, Any]]:
    """Return installed column reflection indexed by name."""
    return {column["name"]: column for column in inspector.get_columns(table_name)}


def test_external_channel_explicit_identifiers_fit_postgresql_limit() -> None:
    """Keep explicit schema identifiers within PostgreSQL's 63-byte limit."""
    identifiers: list[str] = []
    for table in RDBModel.metadata.tables.values():
        if not table.name.startswith("external_channel_"):
            continue
        identifiers.append(table.name)
        identifiers.extend(
            str(constraint.name)
            for constraint in table.constraints
            if constraint.name is not None
        )
        identifiers.extend(
            str(index.name) for index in table.indexes if index.name is not None
        )

    assert identifiers
    assert all(len(identifier.encode()) <= 63 for identifier in identifiers)


def test_external_channel_model_metadata_excludes_retired_inbound_storage() -> None:
    """The application model exposes only retained External Channel authority."""
    model_tables = {
        name
        for name in RDBModel.metadata.tables
        if name.startswith("external_channel_")
    }

    assert _RETIRED_TABLES.isdisjoint(model_tables)
    assert {
        RDBExternalChannelConnection.__tablename__,
        "external_channel_conversation_positions",
        "external_channel_interactions",
        "external_channel_resources",
        "external_channel_bindings",
        "external_channel_access_requests",
        "external_channel_access_grants",
        "external_channel_works",
        "external_channel_actions",
        "external_channel_delivery_attempts",
    } <= model_tables


def test_external_channel_installed_schema_matches_replacement_boundary(
    latest_db_schema: None,
    postgres_container: PostgresContainer,
) -> None:
    """The installed head retains replay state but removes inbound content tables."""
    engine = create_engine(postgres_container.get_connection_url())
    try:
        inspector = inspect(engine)
        installed_tables = set(inspector.get_table_names())
        model_tables = {
            name
            for name in RDBModel.metadata.tables
            if name.startswith("external_channel_")
        }

        assert _RETIRED_TABLES.isdisjoint(installed_tables)
        assert model_tables <= installed_tables

        access_columns = _columns_by_name(
            inspector,
            "external_channel_access_requests",
        )
        assert "trigger_provider_message_key" in access_columns
        assert access_columns["trigger_provider_message_key"]["nullable"] is False
        assert "source_message_id" not in access_columns
        assert {
            "connection_id",
            "conversation_position_id",
            "range_start_position",
            "trigger_position",
        } <= access_columns.keys()

        access_foreign_keys = inspector.get_foreign_keys(
            "external_channel_access_requests"
        )
        assert {
            foreign_key["referred_table"] for foreign_key in access_foreign_keys
        }.isdisjoint(_RETIRED_TABLES)
        assert {
            "external_channel_resources",
            "external_channel_conversation_positions",
        } <= {foreign_key["referred_table"] for foreign_key in access_foreign_keys}

        for table_name in model_tables:
            assert {
                foreign_key["referred_table"]
                for foreign_key in inspector.get_foreign_keys(table_name)
            }.isdisjoint(_RETIRED_TABLES)

        with engine.connect() as connection:
            enum_names = set(
                connection.execute(
                    text(
                        "SELECT typname FROM pg_type "
                        "WHERE typtype = 'e' "
                        "AND typname LIKE 'external_channel_%'"
                    )
                ).scalars()
            )
        assert _RETIRED_ENUMS.isdisjoint(enum_names)
    finally:
        engine.dispose()
