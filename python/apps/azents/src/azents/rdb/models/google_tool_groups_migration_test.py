"""Exercise explicit group conversion against the real predecessor schema."""

import json
from collections.abc import Generator

import pytest
import sqlalchemy as sa
from alembic import command
from cryptography.fernet import Fernet
from sqlalchemy.engine import Engine
from testcontainers.postgres import PostgresContainer

from azents.core.google_policy import GoogleService
from azents.core.google_tool_groups import group_operations, groups_for_services
from azents.core.google_workspace_policy import eligible_model_operations
from azents.testing.migration_database import isolated_migration_database

_PARENT = "d1142f351e96"
_REVISION = "f512e037a843"
_PREFIX = "https://www.googleapis.com/auth/"


@pytest.fixture(scope="module")
def group_predecessor(postgres_container: PostgresContainer) -> Generator[str]:
    with isolated_migration_database(postgres_container, template=None) as database:
        command.upgrade(database.config, _PARENT)
        yield database.name


def _rows(engine: Engine, table: str) -> list[dict[str, object]]:
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                sa.text(f"SELECT * FROM {table} ORDER BY id")
            ).mappings()
        ]


def _seed(engine: Engine, cipher: Fernet, services: list[str]) -> None:
    config = {
        "services": services,
        "oauth_request_scopes": ["openid", "email", _PREFIX + "gmail.readonly"],
        "timeout": 23.0,
    }
    setup = {
        **config,
        "client_id": "client",
        "effective_generation": "generation-secret",
        "redirect_uri": "https://example.test/callback",
        "state_nonce": "state-secret",
        "oidc_nonce": "nonce-secret",
        "code_verifier": "verifier-secret",
        "target": {
            **config,
            "toolkit_id": "google",
            "connection_id": "connection",
            "client_id": "client",
            "subject": "subject-secret",
            "granted_scopes": [_PREFIX + "gmail.modify"],
            "status": "connected",
        },
    }
    final = {
        **config,
        "name": "Existing",
        "slug": "google",
        "description": None,
        "prompt": None,
        "enabled": True,
        "always_expose_tools": bool(services),
    }
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO workspaces(id,name,handle) "
                "VALUES ('workspace','Test','group-migration')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO toolkit_configs(id,workspace_id,owner_kind,"
                "toolkit_type,slug,name,config,enabled) VALUES "
                "('google','workspace','workspace','google','google',"
                "'Google',CAST(:config AS jsonb),true)"
            ),
            {"config": json.dumps(config)},
        )
        connection.execute(
            sa.text(
                "INSERT INTO google_oauth_connections(id,toolkit_id,"
                "client_id,encrypted_payload,status) VALUES "
                "('connection','google','client','opaque-do-not-decode','connected')"
            )
        )
        for identity, status in (
            ("pending", "review"),
            ("published", "published"),
            ("reconnected", "published"),
        ):
            connection.execute(
                sa.text(
                    "INSERT INTO google_oauth_attempts(id,user_id,session_id,"
                    "workspace_id,owner_kind,status,expires_at,encrypted_setup,"
                    "encrypted_candidate,final_settings,published_toolkit_id,"
                    "published_connection_id) VALUES (:id,'user','session',"
                    "'workspace','workspace',:status,now()+interval '1 hour',"
                    ":setup,:candidate,CAST(:final AS jsonb),:toolkit,:connection)"
                ),
                {
                    "id": identity,
                    "status": status,
                    "setup": cipher.encrypt(json.dumps(setup).encode()).decode()
                    if identity == "pending"
                    else None,
                    "candidate": "opaque-candidate" if identity == "pending" else None,
                    "final": json.dumps(final if identity == "published" else config)
                    if status == "published"
                    else None,
                    "toolkit": "google" if status == "published" else None,
                    "connection": "connection" if status == "published" else None,
                },
            )


@pytest.mark.parametrize("services", [[], ["gmail"], ["gmail", "calendar", "drive"]])
def test_conversion_preserves_current_and_staged_authority(
    postgres_container: PostgresContainer,
    group_predecessor: str,
    monkeypatch: pytest.MonkeyPatch,
    services: list[str],
) -> None:
    key = Fernet.generate_key()
    monkeypatch.setenv("AZ_CREDENTIAL_ENCRYPTION_KEY", key.decode())
    cipher = Fernet(key)
    with isolated_migration_database(
        postgres_container, template=group_predecessor
    ) as database:
        _seed(database.engine, cipher, services)
        before_toolkit = _rows(database.engine, "toolkit_configs")[0]
        before_attempts = _rows(database.engine, "google_oauth_attempts")
        before_connections = _rows(database.engine, "google_oauth_connections")
        command.upgrade(database.config, _REVISION)
        expected = sorted(group.value for group in groups_for_services(services))
        old_config = before_toolkit["config"]
        assert isinstance(old_config, dict)
        assert _rows(database.engine, "toolkit_configs")[0] == {
            **before_toolkit,
            "config": {**old_config, "tool_groups": expected},
        }
        assert _rows(database.engine, "google_oauth_connections") == before_connections
        for before, after in zip(
            before_attempts,
            _rows(database.engine, "google_oauth_attempts"),
            strict=True,
        ):
            if before["id"] in {"published", "reconnected"}:
                old_final = before["final_settings"]
                assert isinstance(old_final, dict)
                assert after == {
                    **before,
                    "final_settings": {
                        **old_final,
                        "tool_groups": expected,
                    },
                }
            else:
                old_encrypted = before["encrypted_setup"]
                new_encrypted = after["encrypted_setup"]
                assert isinstance(old_encrypted, str)
                assert isinstance(new_encrypted, str)
                original = json.loads(cipher.decrypt(old_encrypted.encode()))
                updated = json.loads(cipher.decrypt(new_encrypted.encode()))
                assert updated == {
                    **original,
                    "tool_groups": expected,
                    "target": {**original["target"], "tool_groups": expected},
                }
                assert {**after, "encrypted_setup": before["encrypted_setup"]} == before
        enabled = tuple(GoogleService(item) for item in services)
        for grants in (
            None,
            (),
            (_PREFIX + "gmail.readonly",),
            (_PREFIX + "gmail.modify", _PREFIX + "calendar", _PREFIX + "drive"),
        ):
            old = eligible_model_operations(enabled, grants)
            assert old & group_operations(groups_for_services(services)) == old


@pytest.mark.parametrize("defect", ["config", "setup", "target", "final", "key"])
def test_malformed_payload_rolls_back_without_secret_diagnostics(
    postgres_container: PostgresContainer,
    group_predecessor: str,
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
) -> None:
    key = Fernet.generate_key()
    cipher = Fernet(key)
    monkeypatch.setenv("AZ_CREDENTIAL_ENCRYPTION_KEY", key.decode())
    with isolated_migration_database(
        postgres_container, template=group_predecessor
    ) as database:
        _seed(database.engine, cipher, ["gmail"])
        with database.engine.begin() as connection:
            if defect == "config":
                connection.execute(
                    sa.text(
                        "UPDATE toolkit_configs SET config=config || "
                        "'{\"unexpected\":\"secret-canary\"}'::jsonb WHERE id='google'"
                    )
                )
            elif defect == "final":
                connection.execute(
                    sa.text(
                        "UPDATE google_oauth_attempts SET final_settings="
                        "final_settings-'timeout' WHERE id='published'"
                    )
                )
            elif defect == "setup":
                connection.execute(
                    sa.text(
                        "UPDATE google_oauth_attempts "
                        "SET encrypted_setup='secret-canary' WHERE id='pending'"
                    )
                )
            elif defect == "key":
                monkeypatch.setenv(
                    "AZ_CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode()
                )
            else:
                original = connection.scalar(
                    sa.text(
                        "SELECT encrypted_setup FROM google_oauth_attempts "
                        "WHERE id='pending'"
                    )
                )
                setup = json.loads(cipher.decrypt(original.encode()))
                del setup["target"]["services"]
                connection.execute(
                    sa.text(
                        "UPDATE google_oauth_attempts SET encrypted_setup=:setup "
                        "WHERE id='pending'"
                    ),
                    {"setup": cipher.encrypt(json.dumps(setup).encode()).decode()},
                )
        tables = (
            "toolkit_configs",
            "google_oauth_attempts",
            "google_oauth_connections",
            "alembic_version",
        )
        before = {
            table: _rows(database.engine, table)
            for table in tables
            if table != "alembic_version"
        }
        with pytest.raises(ValueError) as caught:
            command.upgrade(database.config, _REVISION)
        assert "secret" not in str(caught.value) and key.decode() not in str(
            caught.value
        )
        assert {table: _rows(database.engine, table) for table in before} == before
        with database.engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == _PARENT
            )
