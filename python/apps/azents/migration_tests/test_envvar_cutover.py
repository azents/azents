"""Encrypted data and consent preservation through the envvar Toolkit cutover."""

import json
from collections.abc import Callable

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

_PARENT = "615047857119"
_REVISION = "409e9e3cb85a"


@pytest.fixture()
def cipher(monkeypatch: pytest.MonkeyPatch) -> Fernet:
    key = Fernet.generate_key()
    monkeypatch.setenv("AZ_CREDENTIAL_ENCRYPTION_KEY", key.decode())
    return Fernet(key)


@pytest.fixture()
def legacy(
    alembic_runner: MigrationContext, alembic_engine: Engine, cipher: Fernet
) -> Callable[..., None]:
    """Seed real predecessor-schema resources, including unattached Agent owners."""
    alembic_runner.migrate_up_to(_PARENT)
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO workspaces (id, name, handle) VALUES "
                "('w', 'Test', 'cutover')"
            )
        )
        connection.execute(
            sa.text("""
            INSERT INTO agents (
                id, workspace_id, name, model_selection, lightweight_model_selection,
                selectable_model_options, main_model_label, lightweight_model_label,
                enabled, type, memory_enabled
            ) SELECT id, 'w', id, '{}'::jsonb, '{}'::jsonb,
                '[{"label":"default","candidates":[{"model_selection":{}}]}]'::jsonb,
                'default', 'default', TRUE, 'public', TRUE
            FROM unnest(ARRAY['a', 'b', 'unrelated']) AS id
        """)
        )

    def add(
        identity: str,
        values: dict[str, str],
        *,
        owner: str | None = None,
        attached: tuple[str, ...] = (),
        enabled: bool = True,
        names: list[str] | None = None,
    ) -> None:
        body = json.dumps({"values": values})
        config = {
            "entries": [
                {"name": name} for name in (names if names is not None else values)
            ]
        }
        with alembic_engine.begin() as connection:
            connection.execute(
                sa.text("""
                INSERT INTO toolkit_configs (
                    id, workspace_id, owner_agent_id, toolkit_type, slug,
                    name, config, encrypted_credentials, enabled
                ) VALUES (:id, 'w', :owner, 'envvar', 'custom_slug',
                    'Custom environment', CAST(:config AS jsonb), :secret, :enabled)
            """),
                {
                    "id": identity,
                    "owner": owner,
                    "config": json.dumps(config),
                    "secret": cipher.encrypt(body.encode()).decode(),
                    "enabled": enabled,
                },
            )
            for agent in attached:
                connection.execute(
                    sa.text("""
                    INSERT INTO agent_toolkits (id, agent_id, toolkit_id, toolkit_type)
                    VALUES (:id, :agent, :toolkit, 'envvar')
                """),
                    {"id": identity + agent, "agent": agent, "toolkit": identity},
                )

    return add


def _local(engine: Engine, cipher: Fernet, agent: str) -> dict[str, str]:
    with engine.connect() as connection:
        encrypted = connection.scalar(
            sa.text("SELECT encrypted_runtime_environment FROM agents WHERE id = :id"),
            {"id": agent},
        )
    return json.loads(cipher.decrypt(encrypted.encode())) if encrypted else {}


def test_migrate_encrypted_values_and_exact_membership(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
    legacy: Callable[..., None],
    cipher: Fernet,
) -> None:
    legacy(
        "owned",
        {"LOCAL": "private-secret", "REMOVED": "do-not-resurrect"},
        owner="a",
        names=["LOCAL"],
    )
    legacy("shared", {"SHARED": "shared-secret", "EMPTY": ""}, attached=("a", "b"))
    legacy("duplicate", {"SHARED": "shared-secret"}, attached=("a",))
    legacy("unattached", {"CATALOG_ONLY": "not-selected"})
    legacy("disabled-empty", {}, enabled=False)
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text("""
            INSERT INTO agent_toolkit_namespace_reservations
                (id, agent_id, toolkit_id, base_slug, ordinal, namespace)
            VALUES ('reservation', 'a', 'owned', 'custom_slug', 1, 'custom_slug')
        """)
        )
        connection.execute(
            sa.text("""
            INSERT INTO toolkit_configs
                (id, workspace_id, toolkit_type, slug, name, config, enabled)
            VALUES ('other', 'w', 'mcp', 'envvar', 'Keep me', '{}'::jsonb, TRUE)
        """)
        )
    alembic_runner.migrate_up_to(_REVISION)
    assert _local(alembic_engine, cipher, "a") == {"LOCAL": "private-secret"}
    assert _local(alembic_engine, cipher, "b") == {}
    with alembic_engine.connect() as connection:
        rows = connection.execute(
            sa.text("SELECT name, encrypted_value FROM workspace_environment_variables")
        ).all()
        assert {
            name: cipher.decrypt(value.encode()).decode() for name, value in rows
        } == {"SHARED": "shared-secret", "EMPTY": "", "CATALOG_ONLY": "not-selected"}
        assert all("shared-secret" not in value for _, value in rows)
        selected = connection.execute(
            sa.text("""
            SELECT s.agent_id, v.name FROM agent_workspace_environment_selections s
            JOIN workspace_environment_variables v ON s.variable_id = v.id
        """)
        ).all()
        assert set(selected) == {
            ("a", "SHARED"),
            ("a", "EMPTY"),
            ("b", "SHARED"),
            ("b", "EMPTY"),
        }
        assert connection.scalar(sa.text("SELECT count(*) FROM agent_toolkits")) == 0
        assert connection.execute(
            sa.text("SELECT id FROM toolkit_configs")
        ).scalars().all() == ["other"]
        assert (
            connection.scalar(
                sa.text("SELECT toolkit_id FROM agent_toolkit_namespace_reservations")
            )
            is None
        )
    # A second Alembic invocation is a no-op; identities and selections survive.
    alembic_runner.migrate_up_to(_REVISION)


@pytest.mark.parametrize(
    "scenario",
    [
        "disabled",
        "sources",
        "workspace-target",
        "local-target",
        "invalid-credential",
        "invalid-config",
        "missing-key",
        "wrong-key",
        "invalid-json",
        "invalid-value",
        "invalid-unicode",
        "limit",
    ],
)
def test_blockers_roll_back_without_secret_disclosure(
    scenario: str,
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
    legacy: Callable[..., None],
    cipher: Fernet,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy("first", {"FIRST": "first-private"}, owner="a")
    legacy(
        "source",
        {"TOKEN": "never-disclose-secret"},
        attached=("a",),
        enabled=scenario != "disabled",
    )
    with alembic_engine.begin() as connection:
        if scenario == "sources":
            legacy("conflicting", {"TOKEN": "different"})
        elif scenario == "workspace-target":
            connection.execute(
                sa.text("""
                INSERT INTO workspace_environment_variables
                (id, workspace_id, name, encrypted_value)
                VALUES ('existing', 'w', 'TOKEN', :value)
            """),
                {"value": cipher.encrypt(b"different").decode()},
            )
        elif scenario == "local-target":
            connection.execute(
                sa.text(
                    "UPDATE agents SET "
                    "encrypted_runtime_environment = :value WHERE id = 'a'"
                ),
                {"value": cipher.encrypt(b'{"FIRST":"different"}').decode()},
            )
        elif scenario == "invalid-credential":
            connection.execute(
                sa.text(
                    "UPDATE toolkit_configs SET "
                    "encrypted_credentials = 'broken' WHERE id = 'source'"
                )
            )
        elif scenario == "invalid-config":
            connection.execute(
                sa.text(
                    "UPDATE toolkit_configs SET config = CAST(:config AS jsonb) "
                    "WHERE id = 'source'"
                ),
                {"config": json.dumps({"entries": [42]})},
            )
        elif scenario == "missing-key":
            monkeypatch.setenv("AZ_CREDENTIAL_ENCRYPTION_KEY", "not-a-fernet-key")
        elif scenario == "wrong-key":
            monkeypatch.setenv(
                "AZ_CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode()
            )
        elif scenario in {"invalid-value", "invalid-unicode", "invalid-json"}:
            value = {
                "invalid-value": "secret\0invalid",
                "invalid-unicode": "secret\ud800invalid",
                "invalid-json": 42,
            }[scenario]
            connection.execute(
                sa.text(
                    "UPDATE toolkit_configs SET "
                    "encrypted_credentials = :value WHERE id = 'source'"
                ),
                {
                    "value": cipher.encrypt(
                        json.dumps({"values": {"TOKEN": value}}).encode()
                    ).decode()
                },
            )
        elif scenario == "limit":
            legacy("too-many", {f"KEY_{i}": "secret" for i in range(51)})
    with pytest.raises(RuntimeError) as caught:
        alembic_runner.migrate_up_to(_REVISION)
    assert "never-disclose-secret" not in str(caught.value)
    assert "first-private" not in str(caught.value)
    with alembic_engine.connect() as connection:
        assert (
            connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
            == _PARENT
        )
        assert (
            connection.scalar(
                sa.text(
                    "SELECT count(*) FROM toolkit_configs WHERE "
                    "id IN ('first', 'source')"
                )
            )
            == 2
        )
        assert connection.scalar(sa.text("SELECT count(*) FROM agent_toolkits")) == 1
        assert (
            connection.scalar(
                sa.text("SELECT count(*) FROM agent_workspace_environment_selections")
            )
            == 0
        )
        assert (
            connection.scalar(
                sa.text(
                    "SELECT count(*) FROM "
                    "workspace_environment_variables WHERE id != 'existing'"
                )
            )
            == 0
        )
    assert _local(alembic_engine, cipher, "a") == (
        {"FIRST": "different"} if scenario == "local-target" else {}
    )


def test_equal_existing_targets_keep_identities_and_selections(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
    legacy: Callable[..., None],
    cipher: Fernet,
) -> None:
    legacy("owned", {"LOCAL": "same"}, owner="a")
    legacy("shared", {"TOKEN": "same"}, attached=("a",))
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE agents SET encrypted_runtime_environment "
                "= :value WHERE id = 'a'"
            ),
            {"value": cipher.encrypt(b'{"LOCAL":"same","OTHER":"retain"}').decode()},
        )
        connection.execute(
            sa.text("""
            INSERT INTO workspace_environment_variables
                (id, workspace_id, name, encrypted_value)
            VALUES ('existing', 'w', 'TOKEN', :value)
        """),
            {"value": cipher.encrypt(b"same").decode()},
        )
        connection.execute(
            sa.text(
                "INSERT INTO "
                "agent_workspace_environment_selections VALUES ('b', 'existing')"
            )
        )
    alembic_runner.migrate_up_to(_REVISION)
    assert _local(alembic_engine, cipher, "a") == {"LOCAL": "same", "OTHER": "retain"}
    with alembic_engine.connect() as connection:
        assert (
            connection.scalar(
                sa.text("SELECT count(*) FROM workspace_environment_variables")
            )
            == 1
        )
        assert set(
            connection.execute(
                sa.text(
                    "SELECT agent_id, variable_id FROM "
                    "agent_workspace_environment_selections"
                )
            ).all()
        ) == {("a", "existing"), ("b", "existing")}


def test_preserve_existing_workspace_precedence(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
    legacy: Callable[..., None],
    cipher: Fernet,
) -> None:
    legacy("owned", {"TOKEN": "toolkit-secret"}, owner="a")
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text("""
            INSERT INTO workspace_environment_variables
                (id, workspace_id, name, encrypted_value)
            VALUES ('existing', 'w', 'TOKEN', :value)
        """),
            {"value": cipher.encrypt(b"workspace-override").decode()},
        )
        connection.execute(
            sa.text(
                "INSERT INTO "
                "agent_workspace_environment_selections VALUES ('a', 'existing')"
            )
        )
    with pytest.raises(RuntimeError, match="Workspace precedence"):
        alembic_runner.migrate_up_to(_REVISION)
    assert _local(alembic_engine, cipher, "a") == {}


def test_owned_values_override_migrated_shared_values(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
    legacy: Callable[..., None],
    cipher: Fernet,
) -> None:
    legacy("owned", {"TOKEN": "owned-secret"}, owner="a")
    legacy("shared", {"TOKEN": "shared-secret"}, attached=("a", "b"))
    alembic_runner.migrate_up_to(_REVISION)
    assert _local(alembic_engine, cipher, "a") == {"TOKEN": "owned-secret"}
    with alembic_engine.connect() as connection:
        assert (
            connection.scalar(
                sa.text("SELECT count(*) FROM agent_workspace_environment_selections")
            )
            == 2
        )


@pytest.mark.parametrize("owner", ["a", None])
def test_cross_workspace_relationships_abort(
    owner: str | None,
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
    legacy: Callable[..., None],
) -> None:
    legacy("source", {"TOKEN": "private"}, owner=owner, attached=("a",))
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO workspaces (id, name, handle) "
                "VALUES ('other', 'Other', 'other-cutover')"
            )
        )
        connection.execute(sa.text("UPDATE toolkit_configs SET workspace_id = 'other'"))
    with pytest.raises(RuntimeError, match="ownership|cross-Workspace"):
        alembic_runner.migrate_up_to(_REVISION)
    with alembic_engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT count(*) FROM toolkit_configs")) == 1


def test_downgrade_refuses_lossy_reconstruction(
    alembic_runner: MigrationContext,
) -> None:
    alembic_runner.migrate_up_to(_REVISION)
    with pytest.raises(RuntimeError, match="irreversible"):
        alembic_runner.migrate_down_to(_PARENT)
