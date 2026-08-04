"""PostgreSQL migration tests for the Session working-folder contract."""

from collections.abc import Generator
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy.exc import DBAPIError
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_EXPAND_PARENT_REVISION = "f6a2c5c503aa"
_EXPAND_REVISION = "5ffa2fdb4e51"
_CONTRACT_REVISION = "155e9db4ee7e"


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


def _seed_root_context(
    connection: sa.Connection,
    *,
    suffix: str,
    handle: str,
    working_folder_path: str | None = None,
) -> str:
    """Seed one root context and return its context ID."""
    workspace_id = f"ws-working-folder-{suffix}"
    agent_id = f"agent-working-folder-{suffix}"
    session_id = f"session-working-folder-{suffix}"
    context_id = f"context-working-folder-{suffix}"
    session_agent_id = f"sa-working-folder-{suffix}"
    connection.execute(sa.text("SET CONSTRAINTS ALL DEFERRED"))
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES (:id, :name, :handle)
            """
        ),
        {
            "id": workspace_id,
            "name": f"Session working folder {suffix}",
            "handle": f"session-working-folder-{suffix}",
        },
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agents (
                id, workspace_id, name, model_selection, lightweight_model_selection,
                selectable_model_options, main_model_label, lightweight_model_label
            )
            VALUES (
                :id,
                :workspace_id,
                :name,
                '{}'::jsonb,
                '{}'::jsonb,
                '[{"label":"default","model_selection":{}}]'::jsonb,
                'default',
                'default'
            )
            """
        ),
        {
            "id": agent_id,
            "workspace_id": workspace_id,
            "name": f"Session working folder Agent {suffix}",
        },
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_sessions (
                id, workspace_id, agent_id, handle, status, start_reason, session_kind
            )
            VALUES (
                :id,
                :workspace_id,
                :agent_id,
                :handle,
                'active',
                'initial',
                'root'
            )
            """
        ),
        {
            "id": session_id,
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "handle": handle,
        },
    )
    context_parameters = {
        "id": context_id,
        "agent_id": agent_id,
        "workspace_id": workspace_id,
    }
    if working_folder_path is None:
        connection.execute(
            sa.text(
                """
                INSERT INTO session_agent_contexts (
                    id, agent_id, workspace_id, root_session_agent_id
                )
                VALUES (:id, :agent_id, :workspace_id, NULL)
                """
            ),
            context_parameters,
        )
    else:
        connection.execute(
            sa.text(
                """
                INSERT INTO session_agent_contexts (
                    id, agent_id, workspace_id, root_session_agent_id,
                    working_folder_path, working_folder_cleanup_status
                )
                VALUES (
                    :id, :agent_id, :workspace_id, NULL,
                    :working_folder_path, 'not_attempted'
                )
                """
            ),
            {
                **context_parameters,
                "working_folder_path": working_folder_path,
            },
        )
    connection.execute(
        sa.text(
            """
            INSERT INTO session_agents (
                id, context_id, root_session_agent_id, agent_session_id, kind,
                name, path, agent_type
            )
            VALUES (
                :id,
                :context_id,
                :id,
                :session_id,
                'root',
                'root',
                '/root',
                'default'
            )
            """
        ),
        {
            "id": session_agent_id,
            "context_id": context_id,
            "session_id": session_id,
        },
    )
    connection.execute(
        sa.text(
            """
            UPDATE session_agent_contexts
            SET root_session_agent_id = :session_agent_id
            WHERE id = :context_id
            """
        ),
        {
            "session_agent_id": session_agent_id,
            "context_id": context_id,
        },
    )
    return context_id


def test_expand_backfills_historical_contexts_to_zero_null_paths(
    check_docker_availability: None,
) -> None:
    """Backfill all valid historical contexts before contract tightening."""
    del check_docker_availability
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _EXPAND_PARENT_REVISION)
        with engine.begin() as connection:
            first_context_id = _seed_root_context(
                connection,
                suffix="first",
                handle="cactus-river-window",
            )
            second_context_id = _seed_root_context(
                connection,
                suffix="second",
                handle="forest-harbor-sunrise",
            )

        alembic_command.upgrade(config, _EXPAND_REVISION)
        with engine.begin() as connection:
            third_context_id = _seed_root_context(
                connection,
                suffix="new",
                handle="ocean-meadow-summit",
                working_folder_path=(
                    "/workspace/agent/.azents/sessions/ocean-meadow-summit"
                ),
            )

        with engine.connect() as connection:
            paths = {
                str(row["id"]): str(row["working_folder_path"])
                for row in connection.execute(
                    sa.text(
                        """
                        SELECT id, working_folder_path
                        FROM session_agent_contexts
                        ORDER BY id
                        """
                    )
                ).mappings()
            }
            zero_null_count = connection.scalar(
                sa.text(
                    """
                    SELECT count(*)
                    FROM session_agent_contexts
                    WHERE working_folder_path IS NULL
                    """
                )
            )
            cleanup_statuses = set(
                connection.execute(
                    sa.text(
                        """
                        SELECT working_folder_cleanup_status::text
                        FROM session_agent_contexts
                        """
                    )
                ).scalars()
            )

        assert paths == {
            first_context_id: "/workspace/agent/.azents/sessions/cactus-river-window",
            second_context_id: (
                "/workspace/agent/.azents/sessions/forest-harbor-sunrise"
            ),
            third_context_id: "/workspace/agent/.azents/sessions/ocean-meadow-summit",
        }
        assert zero_null_count == 0
        assert cleanup_statuses == {"not_attempted"}

        columns = {
            column["name"]: column
            for column in sa.inspect(engine).get_columns("session_agent_contexts")
        }
        assert columns["working_folder_path"]["nullable"] is True
        indexes = {
            index["name"]: index
            for index in sa.inspect(engine).get_indexes("session_agent_contexts")
        }
        assert (
            indexes["ix_session_agent_contexts_working_folder_path"]["unique"] is True
        )


def test_contract_requires_paths_and_replaces_the_transitional_index(
    check_docker_availability: None,
) -> None:
    """Tighten only after the expand backfill supplies every owned path."""
    del check_docker_availability
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _EXPAND_PARENT_REVISION)
        with engine.begin() as connection:
            first_context_id = _seed_root_context(
                connection,
                suffix="c1",
                handle="cactus-river-window",
            )
            second_context_id = _seed_root_context(
                connection,
                suffix="c2",
                handle="forest-harbor-sunrise",
            )

        alembic_command.upgrade(config, _CONTRACT_REVISION)

        inspector = sa.inspect(engine)
        columns = {
            column["name"]: column
            for column in inspector.get_columns("session_agent_contexts")
        }
        assert columns["working_folder_path"]["nullable"] is False
        assert columns["working_folder_cleanup_status"]["nullable"] is False
        assert {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("session_agent_contexts")
        } >= {"uq_session_agent_contexts_working_folder_path"}
        assert "ix_session_agent_contexts_working_folder_path" not in {
            index["name"] for index in inspector.get_indexes("session_agent_contexts")
        }

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        """
                        UPDATE session_agent_contexts
                        SET working_folder_path = NULL
                        WHERE id = :context_id
                        """
                    ),
                    {"context_id": first_context_id},
                )
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        """
                        UPDATE session_agent_contexts
                        SET working_folder_path = (
                            SELECT working_folder_path
                            FROM session_agent_contexts
                            WHERE id = :existing_context_id
                        )
                        WHERE id = :context_id
                        """
                    ),
                    {
                        "context_id": second_context_id,
                        "existing_context_id": first_context_id,
                    },
                )

        alembic_command.downgrade(config, _EXPAND_REVISION)
        downgraded_columns = {
            column["name"]: column
            for column in sa.inspect(engine).get_columns("session_agent_contexts")
        }
        assert downgraded_columns["working_folder_path"]["nullable"] is True
        assert downgraded_columns["working_folder_cleanup_status"]["nullable"] is True
        downgraded_indexes = {
            index["name"]: index
            for index in sa.inspect(engine).get_indexes("session_agent_contexts")
        }
        assert (
            downgraded_indexes["ix_session_agent_contexts_working_folder_path"][
                "unique"
            ]
            is True
        )
