"""Migration integration tests for Team Session resource provenance."""

import importlib
from typing import Any, cast

import sqlalchemy as sa
from alembic import command as alembic_command

_admission_migration = cast(
    Any,
    importlib.import_module(
        "azents.rdb.team_session_admission_provenance_migration_test"
    ),
)
_AGENT_ID: str = _admission_migration._AGENT_ID
_PARENT_REVISION: str = _admission_migration._PARENT_REVISION
_PROVENANCE_REVISION: str = _admission_migration._PROVENANCE_REVISION
_SESSION_ID: str = _admission_migration._SESSION_ID
_USER_ID: str = _admission_migration._USER_ID
_WORKSPACE_ID: str = _admission_migration._WORKSPACE_ID
_migration_database = _admission_migration._migration_database
_seed_legacy_graph = _admission_migration._seed_legacy_graph

_MODEL_LINEAGE_REVISION = "8fae7b9ab00a"
_RESOURCE_PROVENANCE_REVISION = "374a722fb9ee"
_EXACT_RUN_ID = "run-resource-exact"
_EXACT_MODEL_FILE_ID = "model-file-exact"
_UNMATCHED_MODEL_FILE_ID = "model-file-unmatched"
_EXCHANGE_FILE_ID = "exchange-file-migration"


def _seed_legacy_resource_rows(connection: sa.Connection) -> None:
    """Seed pre-Phase-4 resource rows with exact and unavailable lineage."""
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_runs (
                id,
                session_id,
                run_index,
                phase,
                status,
                active_tool_calls
            )
            VALUES (
                :run_id,
                :session_id,
                7,
                'idle',
                'completed',
                '[]'::jsonb
            )
            """
        ),
        {"run_id": _EXACT_RUN_ID, "session_id": _SESSION_ID},
    )
    for model_file_id, run_index in (
        (_EXACT_MODEL_FILE_ID, 7),
        (_UNMATCHED_MODEL_FILE_ID, 99),
    ):
        connection.execute(
            sa.text(
                """
                INSERT INTO model_files (
                    id,
                    workspace_id,
                    session_id,
                    agent_id,
                    media_type,
                    kind,
                    size_bytes,
                    created_run_index,
                    storage_key,
                    normalized_format,
                    sha256,
                    status,
                    metadata
                )
                VALUES (
                    :model_file_id,
                    :workspace_id,
                    :session_id,
                    :agent_id,
                    'image/png',
                    'image',
                    4,
                    :run_index,
                    :storage_key,
                    'png',
                    :sha256,
                    'available',
                    '{}'::jsonb
                )
                """
            ),
            {
                "agent_id": _AGENT_ID,
                "model_file_id": model_file_id,
                "run_index": run_index,
                "session_id": _SESSION_ID,
                "sha256": str(run_index).zfill(64),
                "storage_key": f"model-files/{model_file_id}",
                "workspace_id": _WORKSPACE_ID,
            },
        )
    connection.execute(
        sa.text(
            """
            INSERT INTO exchange_files (
                id,
                workspace_id,
                agent_id,
                origin_type,
                object_key,
                filename,
                media_type,
                size_bytes,
                sha256,
                created_by_user_id,
                status
            )
            VALUES (
                :exchange_file_id,
                :workspace_id,
                :agent_id,
                'upload',
                'exchange/migration-file',
                'migration-file.txt',
                'text/plain',
                4,
                :sha256,
                :user_id,
                'available'
            )
            """
        ),
        {
            "agent_id": _AGENT_ID,
            "exchange_file_id": _EXCHANGE_FILE_ID,
            "sha256": "1" * 64,
            "user_id": _USER_ID,
            "workspace_id": _WORKSPACE_ID,
        },
    )


def test_team_session_resource_provenance_migrations(
    check_docker_availability: None,
) -> None:
    """Preserve exact known lineage and leave unavailable history unsynthesized."""
    del check_docker_availability
    migration_database = _migration_database()
    config, engine = next(migration_database)
    try:
        alembic_command.upgrade(config, _PARENT_REVISION)
        with engine.begin() as connection:
            _seed_legacy_graph(connection)
        alembic_command.upgrade(config, _PROVENANCE_REVISION)
        with engine.begin() as connection:
            _seed_legacy_resource_rows(connection)

        alembic_command.upgrade(config, _MODEL_LINEAGE_REVISION)
        with engine.connect() as connection:
            model_lineage = {
                row.id: row.created_run_id
                for row in connection.execute(
                    sa.text(
                        """
                        SELECT id, created_run_id
                        FROM model_files
                        WHERE id IN (:exact_id, :unmatched_id)
                        ORDER BY id
                        """
                    ),
                    {
                        "exact_id": _EXACT_MODEL_FILE_ID,
                        "unmatched_id": _UNMATCHED_MODEL_FILE_ID,
                    },
                ).mappings()
            }
        assert model_lineage == {
            _EXACT_MODEL_FILE_ID: _EXACT_RUN_ID,
            _UNMATCHED_MODEL_FILE_ID: None,
        }

        alembic_command.upgrade(config, _RESOURCE_PROVENANCE_REVISION)
        with engine.connect() as connection:
            exchange_provenance = connection.execute(
                sa.text(
                    """
                    SELECT provenance_kind, source_user_id, source_run_id
                    FROM exchange_files
                    WHERE id = :exchange_file_id
                    """
                ),
                {"exchange_file_id": _EXCHANGE_FILE_ID},
            ).one()
            exchange_columns = set(
                connection.scalars(
                    sa.text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'exchange_files'
                        """
                    )
                )
            )

        assert exchange_provenance.provenance_kind == "migration"
        assert exchange_provenance.source_user_id == _USER_ID
        assert exchange_provenance.source_run_id is None
        assert "created_by_user_id" not in exchange_columns
    finally:
        try:
            next(migration_database)
        except StopIteration:
            pass
