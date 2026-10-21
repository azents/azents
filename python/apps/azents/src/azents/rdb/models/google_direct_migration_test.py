"""Run the stopped Google cutover on isolated real predecessor databases."""

import json
from collections.abc import Generator
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import Engine
from testcontainers.postgres import PostgresContainer
from uuid6 import uuid7

from azents.testing.migration_database import isolated_migration_database
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)

_PREDECESSOR = "2944b0e66140"
_REVISION = "d1142f351e96"
_SCOPE = "https://www.googleapis.com/auth/"
_ENDPOINT = "https://drivemcp.googleapis.com/mcp/v1"
_TASKS = {
    "calendar_read": (
        "calendar",
        ("calendar.events.readonly", "calendar.calendarlist.readonly"),
    ),
    "calendar_availability": (
        "calendar",
        ("calendar.events.freebusy", "calendar.calendarlist.readonly"),
    ),
    "calendar_edit": ("calendar", ("calendar.events",)),
    "drive_read": ("drive", ("drive.readonly",)),
    "drive_files": ("drive", ("drive.file",)),
    "gmail_read": ("gmail", ("gmail.readonly",)),
    "gmail_drafts": ("gmail", ("gmail.compose",)),
    "gmail_modify": ("gmail", ("gmail.modify",)),
}


@pytest.fixture(scope="module")
def predecessor(postgres_container: PostgresContainer) -> Generator[str]:
    with isolated_migration_database(postgres_container, template=None) as database:
        command.upgrade(database.config, _PREDECESSOR)
        yield database.name


@dataclass(frozen=True)
class Seed:
    toolkit: str
    pending: str
    published: str
    snapshot: str
    working: str


def _old(tasks: list[str]) -> dict[str, object]:
    return {"tasks": tasks, "security_risk_acknowledged": False, "timeout": 23}


def _seed(engine: Engine, *, owner: str, config: object, final: object) -> Seed:
    (
        workspace,
        agent,
        session,
        user,
        email,
        toolkit,
        grant,
        pending,
        published,
        snapshot,
        working,
    ) = (uuid7().hex for _ in range(11))
    model = make_test_model_selection_dict()
    options = make_test_selectable_model_option_dicts(
        model_selection=model, lightweight_model_selection=model
    )
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO workspaces(id,name,handle) "
                "VALUES (:id,'Google cutover',:id)"
            ),
            {"id": workspace},
        )
        connection.execute(
            sa.text("INSERT INTO users(id,primary_email_id) VALUES (:id,:email)"),
            {"id": user, "email": email},
        )
        connection.execute(
            sa.text(
                "INSERT INTO user_emails(id,user_id,email) VALUES (:id,:user,:email)"
            ),
            {"id": email, "user": user, "email": user + "@example.test"},
        )
        connection.execute(
            sa.text(
                "INSERT INTO agents(id,workspace_id,name,model_selection,"
                "lightweight_model_selection,selectable_model_options,"
                "main_model_label,lightweight_model_label,enabled,type,memory_enabled) "
                "VALUES (:id,:workspace,'Google cutover',CAST(:model AS jsonb),"
                "CAST(:model AS jsonb),CAST(:options AS jsonb),"
                "'default','lightweight',true,'public',true)"
            ),
            {
                "id": agent,
                "workspace": workspace,
                "model": json.dumps(model),
                "options": json.dumps(options),
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO agent_sessions"
                "(id,workspace_id,agent_id,status,start_reason) "
                "VALUES (:id,:workspace,:agent,'active','initial')"
            ),
            {"id": session, "workspace": workspace, "agent": agent},
        )
        connection.execute(
            sa.text(
                "INSERT INTO toolkit_configs(id,workspace_id,owner_kind,"
                "owner_agent_id,owner_user_id,personal_access_mode,toolkit_type,"
                "slug,name,config,encrypted_credentials,enabled,description,"
                "prompt,revision) VALUES (:id,:workspace,:owner,:agent,:user,"
                ":mode,'google','google','Preserved',CAST(:config AS jsonb),"
                "'opaque-toolkit-secret',false,'Description','Prompt',7)"
            ),
            {
                "id": toolkit,
                "workspace": workspace,
                "owner": owner,
                "agent": agent if owner == "agent" else None,
                "user": user if owner == "user" else None,
                "mode": "all" if owner == "user" else None,
                "config": json.dumps(config),
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO google_oauth_connections"
                "(id,toolkit_id,client_id,encrypted_payload,status) "
                "VALUES (:id,:toolkit,'same-client',"
                "'opaque-encrypted-actual-grant','connected')"
            ),
            {"id": grant, "toolkit": toolkit},
        )
        for attempt, status, payload in (
            (pending, "review", {"malformed_retired": True}),
            (published, "published", final),
        ):
            connection.execute(
                sa.text(
                    "INSERT INTO google_oauth_attempts(id,user_id,session_id,"
                    "workspace_id,owner_kind,owner_user_id,agent_id,"
                    "target_toolkit_id,encrypted_setup,encrypted_candidate,"
                    "status,expires_at,published_toolkit_id,"
                    "published_connection_id,final_settings) VALUES "
                    "(:id,:user,:session,:workspace,:owner,:owner_user,:agent,"
                    ":toolkit,'unparseable-setup','unparseable-candidate',"
                    ":status,now()+interval '1 hour',:out_toolkit,"
                    ":out_connection,CAST(:final AS jsonb))"
                ),
                {
                    "id": attempt,
                    "user": user,
                    "session": session,
                    "workspace": workspace,
                    "owner": owner,
                    "owner_user": user if owner == "user" else None,
                    "agent": agent if owner == "agent" else None,
                    "toolkit": toolkit,
                    "status": status,
                    "out_toolkit": toolkit if status == "published" else None,
                    "out_connection": "historical-replaced-connection"
                    if status == "published"
                    else None,
                    "final": json.dumps(payload),
                },
            )
        connection.execute(
            sa.text(
                "INSERT INTO agent_toolkit_namespace_reservations"
                "(id,agent_id,toolkit_id,base_slug,ordinal,namespace) "
                "VALUES (:id,:agent,:toolkit,'google',1,'google')"
            ),
            {"id": uuid7().hex, "agent": agent, "toolkit": toolkit},
        )
        snapshot_payload = {
            "schema_version": 1,
            "server_url": _ENDPOINT,
            "tools": [
                {
                    "raw_name": "search_files",
                    "model_name": "search_files",
                    "description": "legacy",
                    "input_schema": {"type": "object"},
                    "server_url": _ENDPOINT,
                    "use_streamable_http": True,
                }
            ],
        }
        for state_id, namespace, name, payload in (
            (snapshot, "mcp", f"google:{toolkit}:drive", snapshot_payload),
            (
                working,
                "tool_search",
                "working_set",
                {
                    "schema_version": 1,
                    "tool_names": [
                        "other__drive_search_files",
                        "google__drive_search_files",
                        "google__gmail_get_message",
                        "other__read",
                    ],
                },
            ),
            (uuid7().hex, "mcp", "tool_snapshot", {"unrelated": "preserved"}),
            (uuid7().hex, "notes", "keep", {"unrelated": [1, 2, 3]}),
        ):
            connection.execute(
                sa.text(
                    "INSERT INTO toolkit_states(id,agent_id,session_id,"
                    "toolkit_namespace,state_name,state_json,schema_version,version) "
                    "VALUES (:id,:agent,:session,:namespace,:name,"
                    "CAST(:payload AS jsonb),1,4)"
                ),
                {
                    "id": state_id,
                    "agent": agent,
                    "session": session,
                    "namespace": namespace,
                    "name": name,
                    "payload": json.dumps(payload),
                },
            )
    return Seed(toolkit, pending, published, snapshot, working)


def _rows(engine: Engine, table: str) -> list[dict[str, object]]:
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                sa.text(f"SELECT * FROM {table} ORDER BY id")
            ).mappings()
        ]


@pytest.mark.parametrize("owner", ["workspace", "agent", "user"])
@pytest.mark.parametrize("task", list(_TASKS))
def test_cutover_preserves_owner_grant_and_historical_identity(
    postgres_container: PostgresContainer, predecessor: str, owner: str, task: str
) -> None:
    with isolated_migration_database(
        postgres_container, template=predecessor
    ) as database:
        seed = _seed(
            database.engine, owner=owner, config=_old([task]), final=_old([task])
        )
        before_config = _rows(database.engine, "toolkit_configs")[0]
        before_grants = _rows(database.engine, "google_oauth_connections")
        before_attempts = {
            row["id"]: row for row in _rows(database.engine, "google_oauth_attempts")
        }
        before_states = _rows(database.engine, "toolkit_states")
        before_reservations = _rows(
            database.engine, "agent_toolkit_namespace_reservations"
        )
        command.upgrade(database.config, _REVISION)
        after = _rows(database.engine, "toolkit_configs")[0]
        service, scopes = _TASKS[task]
        expected = {
            "services": [service],
            "oauth_request_scopes": sorted(
                {"openid", "email", *(_SCOPE + scope for scope in scopes)}
            ),
            "timeout": 23.0,
        }
        assert after == {**before_config, "config": expected}
        assert _rows(database.engine, "google_oauth_connections") == before_grants
        assert (
            _rows(database.engine, "agent_toolkit_namespace_reservations")
            == before_reservations
        )
        for row in _rows(database.engine, "google_oauth_attempts"):
            old = before_attempts[row["id"]]
            assert row == {
                **old,
                "encrypted_setup": None,
                "encrypted_candidate": None,
                "status": "published" if row["id"] == seed.published else "cancelled",
                "final_settings": expected if row["id"] == seed.published else None,
            }
        after_states = {
            row["id"]: row for row in _rows(database.engine, "toolkit_states")
        }
        assert seed.snapshot not in after_states
        for row in before_states:
            if row["id"] == seed.snapshot:
                continue
            if row["id"] == seed.working:
                assert after_states[row["id"]] == {
                    **row,
                    "state_json": {
                        "schema_version": 1,
                        "tool_names": ["other__drive_search_files", "other__read"],
                    },
                }
            else:
                assert after_states[row["id"]] == row
        # An administrative rerun recognizes transformed config/outcome state.
        stable = {
            table: _rows(database.engine, table)
            for table in ("toolkit_configs", "google_oauth_attempts", "toolkit_states")
        }
        command.stamp(database.config, _PREDECESSOR)
        command.upgrade(database.config, _REVISION)
        assert {table: _rows(database.engine, table) for table in stable} == stable


@pytest.mark.parametrize(
    "malformed",
    [
        {"tasks": ["invented"], "security_risk_acknowledged": True},
        {"tasks": ["gmail_read"], "security_risk_acknowledged": "true"},
        {"tasks": ["gmail_read"], "security_risk_acknowledged": True, "timeout": "30"},
        {"tasks": ["gmail_read"], "security_risk_acknowledged": True, "timeout": True},
        {"tasks": [], "security_risk_acknowledged": True},
        {"services": ["gmail"], "oauth_request_scopes": ["unknown"], "timeout": 30},
        {"tasks": ["gmail_read"], "security_risk_acknowledged": True, "services": []},
        None,
    ],
)
def test_invalid_config_aborts_all_writes(
    postgres_container: PostgresContainer, predecessor: str, malformed: object
) -> None:
    with isolated_migration_database(
        postgres_container, template=predecessor
    ) as database:
        _seed(
            database.engine,
            owner="workspace",
            config=malformed,
            final=_old(["drive_files"]),
        )
        tables = (
            "toolkit_configs",
            "google_oauth_connections",
            "google_oauth_attempts",
            "toolkit_states",
            "agent_toolkit_namespace_reservations",
        )
        before = {table: _rows(database.engine, table) for table in tables}
        with pytest.raises(ValueError, match="Google") as error:
            command.upgrade(database.config, _REVISION)
        assert "opaque" not in str(error.value)
        assert {table: _rows(database.engine, table) for table in tables} == before
        with database.engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == _PREDECESSOR
            )


@pytest.mark.parametrize(
    "defect",
    ["missing_timeout", "partial_metadata", "identity", "snapshot", "orphan_recency"],
)
def test_late_preflight_failure_preserves_every_earlier_valid_row(
    postgres_container: PostgresContainer, predecessor: str, defect: str
) -> None:
    with isolated_migration_database(
        postgres_container, template=predecessor
    ) as database:
        seed = _seed(
            database.engine,
            owner="workspace",
            config=_old(["drive_files"]),
            final=_old(["drive_files"]),
        )
        with database.engine.begin() as connection:
            if defect == "missing_timeout":
                connection.execute(
                    sa.text(
                        "UPDATE google_oauth_attempts "
                        "SET final_settings=final_settings-'timeout' WHERE id=:id"
                    ),
                    {"id": seed.published},
                )
            elif defect == "partial_metadata":
                connection.execute(
                    sa.text(
                        "UPDATE google_oauth_attempts SET final_settings="
                        'final_settings || \'{"name":"canary"}\'::jsonb WHERE id=:id'
                    ),
                    {"id": seed.published},
                )
            elif defect == "identity":
                connection.execute(
                    sa.text(
                        "UPDATE google_oauth_attempts "
                        "SET published_connection_id=NULL WHERE id=:id"
                    ),
                    {"id": seed.published},
                )
            elif defect == "snapshot":
                connection.execute(
                    sa.text(
                        "UPDATE toolkit_states SET state_json=jsonb_set("
                        "state_json,'{server_url}',"
                        "'\"https://unrelated.example/mcp\"') WHERE id=:id"
                    ),
                    {"id": seed.snapshot},
                )
            else:
                connection.execute(
                    sa.text("DELETE FROM agent_toolkit_namespace_reservations")
                )
        tables = (
            "toolkit_configs",
            "google_oauth_attempts",
            "google_oauth_connections",
            "toolkit_states",
        )
        before = {table: _rows(database.engine, table) for table in tables}
        with pytest.raises(ValueError, match="Google"):
            command.upgrade(database.config, _REVISION)
        assert {table: _rows(database.engine, table) for table in tables} == before


def test_default_timeout_mixed_scopes_and_creation_metadata(
    postgres_container: PostgresContainer, predecessor: str
) -> None:
    metadata = {
        "name": "Historical",
        "slug": "google",
        "description": "Kept",
        "prompt": None,
        "enabled": False,
        "always_expose_tools": True,
    }
    with isolated_migration_database(
        postgres_container, template=predecessor
    ) as database:
        config = _old(["drive_files", "drive_read", "drive_files"])
        config.pop("timeout")
        seed = _seed(
            database.engine,
            owner="workspace",
            config=config,
            final={**_old(["drive_files", "drive_read"]), **metadata},
        )
        command.upgrade(database.config, _REVISION)
        saved = _rows(database.engine, "toolkit_configs")[0]["config"]
        assert isinstance(saved, dict)
        assert saved == {
            "services": ["drive"],
            "oauth_request_scopes": sorted(
                ["openid", "email", _SCOPE + "drive.file", _SCOPE + "drive.readonly"]
            ),
            "timeout": 30,
        }
        outcome = next(
            row
            for row in _rows(database.engine, "google_oauth_attempts")
            if row["id"] == seed.published
        )
        assert outcome["final_settings"] == {**saved, **metadata, "timeout": 23}


def test_empty_cutover_and_explicit_checkpoint_only_downgrade(
    postgres_container: PostgresContainer, predecessor: str
) -> None:
    with isolated_migration_database(
        postgres_container, template=predecessor
    ) as database:
        command.upgrade(database.config, _REVISION)
        assert _rows(database.engine, "toolkit_configs") == []
        with pytest.raises(RuntimeError, match="irreversible"):
            command.downgrade(database.config, _PREDECESSOR)


@pytest.mark.parametrize(
    "defect",
    [
        "grant_type",
        "owner_workspace",
        "attempt_workspace",
        "working_session",
        "reservation_agent",
        "reservation_workspace",
    ],
)
def test_cutover_checks_relational_ownership_without_reading_grant_secrets(
    postgres_container: PostgresContainer, predecessor: str, defect: str
) -> None:
    with isolated_migration_database(
        postgres_container, template=predecessor
    ) as database:
        seed = _seed(
            database.engine,
            owner="agent",
            config=_old(["drive_files"]),
            final=_old(["drive_files"]),
        )
        with database.engine.begin() as connection:
            if defect == "grant_type":
                connection.execute(
                    sa.text(
                        "UPDATE toolkit_configs SET toolkit_type='mcp' WHERE id=:id"
                    ),
                    {"id": seed.toolkit},
                )
                connection.execute(
                    sa.text("DELETE FROM toolkit_states WHERE id=:id"),
                    {"id": seed.snapshot},
                )
            elif defect in (
                "working_session",
                "reservation_agent",
                "reservation_workspace",
            ):
                workspace = connection.scalar(
                    sa.text("SELECT workspace_id FROM toolkit_configs WHERE id=:id"),
                    {"id": seed.toolkit},
                )
                if defect == "reservation_workspace":
                    workspace = uuid7().hex
                    connection.execute(
                        sa.text(
                            "INSERT INTO workspaces(id,name,handle) "
                            "VALUES (:id,'Other',:id)"
                        ),
                        {"id": workspace},
                    )
                new_agent, new_session = uuid7().hex, uuid7().hex
                connection.execute(
                    sa.text(
                        "INSERT INTO agents(id,workspace_id,name,model_selection,"
                        "lightweight_model_selection,selectable_model_options,"
                        "main_model_label,lightweight_model_label,"
                        "enabled,type,memory_enabled) "
                        "SELECT :agent,:workspace,'Other',a.model_selection,"
                        "a.lightweight_model_selection,a.selectable_model_options,"
                        "a.main_model_label,a.lightweight_model_label,"
                        "true,'public',true "
                        "FROM agents a JOIN toolkit_configs t ON t.owner_agent_id=a.id "
                        "WHERE t.id=:toolkit"
                    ),
                    {
                        "agent": new_agent,
                        "workspace": workspace,
                        "toolkit": seed.toolkit,
                    },
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO agent_sessions"
                        "(id,workspace_id,agent_id,status,start_reason) "
                        "VALUES (:id,:workspace,:agent,'active','initial')"
                    ),
                    {"id": new_session, "workspace": workspace, "agent": new_agent},
                )
                if defect == "working_session":
                    connection.execute(
                        sa.text(
                            "UPDATE toolkit_states SET session_id=:session WHERE id=:id"
                        ),
                        {"session": new_session, "id": seed.working},
                    )
                else:
                    connection.execute(
                        sa.text("DELETE FROM toolkit_states WHERE id=:id"),
                        {"id": seed.snapshot},
                    )
                    connection.execute(
                        sa.text(
                            "UPDATE agent_toolkit_namespace_reservations "
                            "SET agent_id=:agent WHERE toolkit_id=:toolkit"
                        ),
                        {"agent": new_agent, "toolkit": seed.toolkit},
                    )
                    connection.execute(
                        sa.text(
                            "UPDATE toolkit_states SET agent_id=:agent,"
                            "session_id=:session "
                            "WHERE id=:id"
                        ),
                        {
                            "agent": new_agent,
                            "session": new_session,
                            "id": seed.working,
                        },
                    )
            else:
                workspace = uuid7().hex
                connection.execute(
                    sa.text(
                        "INSERT INTO workspaces(id,name,handle) "
                        "VALUES (:id,'Other',:id)"
                    ),
                    {"id": workspace},
                )
                statement = (
                    "UPDATE toolkit_configs SET workspace_id=:workspace WHERE id=:id"
                    if defect == "owner_workspace"
                    else "UPDATE google_oauth_attempts SET workspace_id=:workspace "
                    "WHERE id=:id"
                )
                connection.execute(
                    sa.text(statement),
                    {
                        "id": seed.toolkit
                        if defect == "owner_workspace"
                        else seed.pending,
                        "workspace": workspace,
                    },
                )
        tables = (
            "toolkit_configs",
            "google_oauth_attempts",
            "google_oauth_connections",
            "toolkit_states",
        )
        before = {table: _rows(database.engine, table) for table in tables}
        before_reservations = _rows(
            database.engine, "agent_toolkit_namespace_reservations"
        )
        before_sessions = _rows(database.engine, "agent_sessions")
        with pytest.raises(ValueError, match="Google ownership relationship"):
            command.upgrade(database.config, _REVISION)
        assert {table: _rows(database.engine, table) for table in tables} == before
        assert (
            _rows(database.engine, "agent_toolkit_namespace_reservations")
            == before_reservations
        )
        assert _rows(database.engine, "agent_sessions") == before_sessions


@pytest.mark.parametrize(
    "status", ["pending", "exchanging", "review", "failed", "cancelled"]
)
def test_unpublished_attempts_are_terminal_before_any_retired_payload_decode(
    postgres_container: PostgresContainer, predecessor: str, status: str
) -> None:
    with isolated_migration_database(
        postgres_container, template=predecessor
    ) as database:
        all_off = {
            "services": [],
            "oauth_request_scopes": ["openid", "email", _SCOPE + "drive.file"],
            "timeout": 30,
        }
        seed = _seed(database.engine, owner="workspace", config=all_off, final=all_off)
        with database.engine.begin() as connection:
            connection.execute(
                sa.text("UPDATE google_oauth_attempts SET status=:status WHERE id=:id"),
                {"status": status, "id": seed.pending},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO toolkit_configs(id,workspace_id,owner_kind,"
                    "toolkit_type,slug,name,config,enabled) "
                    "SELECT :id,workspace_id,'workspace','mcp','other','Other',"
                    '\'{"server_url":"https://unrelated.example/mcp"}\'::jsonb,true '
                    "FROM toolkit_configs WHERE id=:google"
                ),
                {"id": uuid7().hex, "google": seed.toolkit},
            )
        before = _rows(database.engine, "toolkit_configs")
        command.upgrade(database.config, _REVISION)
        after = _rows(database.engine, "toolkit_configs")
        for old, current in zip(before, after, strict=True):
            if old["id"] == seed.toolkit:
                assert current == {
                    **old,
                    "config": {
                        **all_off,
                        "oauth_request_scopes": sorted(
                            ["openid", "email", _SCOPE + "drive.file"]
                        ),
                    },
                }
            else:
                assert current == old
        pending = next(
            row
            for row in _rows(database.engine, "google_oauth_attempts")
            if row["id"] == seed.pending
        )
        assert pending["status"] == "cancelled"
        assert pending["encrypted_setup"] is None
        assert pending["encrypted_candidate"] is None
        assert pending["final_settings"] is None
