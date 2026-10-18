"""Primary migration preserves connections and rejects ambiguous legacy data."""

import json
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from alembic import command
from azcommon.uuid import uuid7
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from testcontainers.postgres import PostgresContainer

from azents.core.enums import LLMProvider
from azents.testing.migration_database import isolated_migration_database
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)

_PREDECESSOR = "004bda2b6938"
_REVISION = "08a588456917"


@dataclass(frozen=True)
class _LegacyData:
    session_id: str
    binding_ids: tuple[str, ...]


def _seed_legacy(engine: Engine, *, binding_count: int) -> _LegacyData:
    """Seed actual predecessor columns, independent of current ORM mappings."""
    workspace_id, agent_id, session_id = (uuid7().hex for _ in range(3))
    model = make_test_model_selection_dict(
        integration_id=uuid7().hex,
        provider=LLMProvider.ANTHROPIC,
        model_identifier="routine-migration-fixture",
    )
    options = make_test_selectable_model_option_dicts(
        model_selection=model, lightweight_model_selection=model
    )
    binding_ids: list[str] = []
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO workspaces(id,name,handle) "
                "VALUES (:id,'Routine migration',:handle)"
            ),
            {"id": workspace_id, "handle": f"routine-{workspace_id}"},
        )
        connection.execute(
            sa.text(
                "INSERT INTO agents(id,workspace_id,name,model_selection,"
                "lightweight_model_selection,selectable_model_options,"
                "main_model_label,lightweight_model_label,enabled,type,memory_enabled) "
                "VALUES (:id,:workspace,'Routine migration',CAST(:model AS jsonb),"
                "CAST(:model AS jsonb),CAST(:options AS jsonb),"
                "'default','lightweight',true,'public',true)"
            ),
            {
                "id": agent_id,
                "workspace": workspace_id,
                "model": json.dumps(model),
                "options": json.dumps(options),
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO agent_sessions"
                "(id,workspace_id,agent_id,status,start_reason) "
                "VALUES (:id,:workspace,:agent,'active','external_channel')"
            ),
            {"id": session_id, "workspace": workspace_id, "agent": agent_id},
        )
        for _ in range(binding_count):
            connection_id, route_id, resource_id, binding_id = (
                uuid7().hex for _ in range(4)
            )
            connection.execute(
                sa.text(
                    "INSERT INTO external_channel_connections "
                    "(id,workspace_id,provider,transport,status,app_mode) "
                    "VALUES (:id,:workspace,'slack','http','active','single')"
                ),
                {"id": connection_id, "workspace": workspace_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO external_channel_agent_routes "
                    "(id,connection_id,agent_id,agent_id_snapshot,route_mode,"
                    "connection_app_mode,catalog_status) "
                    "VALUES (:id,:connection,:agent,:agent,'dedicated','single',"
                    "'available')"
                ),
                {"id": route_id, "connection": connection_id, "agent": agent_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO external_channel_resources "
                    "(id,connection_id,resource_type,provider_resource_key,status) "
                    "VALUES (:id,:connection,'thread',:resource_key,'active')"
                ),
                {
                    "id": resource_id,
                    "connection": connection_id,
                    "resource_key": f"thread-{resource_id}",
                },
            )
            connection.execute(
                sa.text(
                    "INSERT INTO external_channel_bindings "
                    "(id,resource_id,route_id,agent_session_id,response_mode) "
                    "VALUES (:id,:resource,:route,:session,'all_messages')"
                ),
                {
                    "id": binding_id,
                    "resource": resource_id,
                    "route": route_id,
                    "session": session_id,
                },
            )
            binding_ids.append(binding_id)
    return _LegacyData(session_id=session_id, binding_ids=tuple(binding_ids))


@pytest.mark.parametrize("binding_count", [0, 1])
def test_primary_migration_backfills_without_replacing_connections(
    postgres_container: PostgresContainer, binding_count: int
) -> None:
    with isolated_migration_database(postgres_container, template=None) as database:
        command.upgrade(database.config, _PREDECESSOR)
        legacy = _seed_legacy(database.engine, binding_count=binding_count)
        command.upgrade(database.config, _REVISION)
        with database.engine.connect() as connection:
            primary = connection.scalar(
                sa.text(
                    "SELECT primary_channel_binding_id FROM agent_sessions WHERE id=:id"
                ),
                {"id": legacy.session_id},
            )
            assert primary == (legacy.binding_ids[0] if legacy.binding_ids else None)
            retained = (
                connection.execute(
                    sa.text("SELECT id FROM external_channel_bindings ORDER BY id")
                )
                .scalars()
                .all()
            )
            assert retained == list(legacy.binding_ids)
            assert sa.inspect(connection).has_table("routines")
            assert sa.inspect(connection).has_table("routine_work_records")


def test_ambiguous_primary_migration_rolls_back_before_any_designation(
    postgres_container: PostgresContainer,
) -> None:
    with isolated_migration_database(postgres_container, template=None) as database:
        command.upgrade(database.config, _PREDECESSOR)
        legacy = _seed_legacy(database.engine, binding_count=2)
        with pytest.raises(DBAPIError, match="multiple connected Bindings"):
            command.upgrade(database.config, _REVISION)
        with database.engine.connect() as connection:
            columns = sa.inspect(connection).get_columns("agent_sessions")
            assert "primary_channel_binding_id" not in {
                column["name"] for column in columns
            }
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == _PREDECESSOR
            )
            assert connection.execute(
                sa.text("SELECT id FROM external_channel_bindings ORDER BY id")
            ).scalars().all() == list(legacy.binding_ids)


@pytest.mark.parametrize("bad_owner", ["inactive_connection", "cross_workspace"])
def test_primary_migration_rejects_incompatible_connection_authority(
    postgres_container: PostgresContainer,
    bad_owner: str,
) -> None:
    with isolated_migration_database(postgres_container, template=None) as database:
        command.upgrade(database.config, _PREDECESSOR)
        _seed_legacy(database.engine, binding_count=1)
        with database.engine.begin() as connection:
            if bad_owner == "inactive_connection":
                connection.execute(
                    sa.text(
                        "UPDATE external_channel_connections SET status='disconnected',"
                        "disconnected_at=now()"
                    )
                )
            else:
                foreign_workspace = uuid7().hex
                connection.execute(
                    sa.text(
                        "INSERT INTO workspaces(id,name,handle) "
                        "VALUES (:id,'Foreign fixture',:handle)"
                    ),
                    {
                        "id": foreign_workspace,
                        "handle": f"foreign-{foreign_workspace}",
                    },
                )
                connection.execute(
                    sa.text(
                        "UPDATE external_channel_connections "
                        "SET workspace_id=:workspace"
                    ),
                    {"workspace": foreign_workspace},
                )
        with pytest.raises(DBAPIError, match="incompatible Binding owners"):
            command.upgrade(database.config, _REVISION)
        with database.engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == _PREDECESSOR
            )
