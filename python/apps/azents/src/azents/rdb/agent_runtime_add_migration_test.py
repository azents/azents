"""Migration tests for durable Agent Runtime addition receipts."""

from collections.abc import Generator
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from testcontainers.postgres import PostgresContainer

from azents.consts import PROJECT_ROOT

_PARENT_REVISION = "8b9f418cf037"
_RECEIPT_REVISION = "114473afc4be"


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


def test_runtime_add_receipt_migration_upgrades_and_downgrades(
    check_docker_availability: None,
) -> None:
    """The additive receipt table cleanly round-trips from its parent revision."""
    del check_docker_availability
    with _migration_database() as (config, engine):
        alembic_command.upgrade(config, _PARENT_REVISION)
        assert "agent_runtime_add_receipts" not in sa.inspect(engine).get_table_names()

        alembic_command.upgrade(config, _RECEIPT_REVISION)
        inspector = sa.inspect(engine)
        assert "agent_runtime_add_receipts" in inspector.get_table_names()
        assert {
            column["name"]
            for column in inspector.get_columns("agent_runtime_add_receipts")
        } == {
            "id",
            "agent_id",
            "workspace_id",
            "idempotency_key",
            "workspace_runtime_profile_id",
            "expected_capability_version",
            "committed_capability_version",
            "committed_runtime_profile_selection_version",
            "agent_runtime_id",
            "runtime_configuration_revision_id",
            "runtime_desired_generation",
            "created_at",
        }
        indexes = {
            index["name"]: index
            for index in inspector.get_indexes("agent_runtime_add_receipts")
        }
        assert (
            indexes["uq_agent_runtime_add_receipts_agent_idempotency"]["unique"] is True
        )
        assert indexes["uq_agent_runtime_add_receipts_agent_idempotency"][
            "column_names"
        ] == ["agent_id", "idempotency_key"]
        assert {
            constraint["name"]
            for constraint in inspector.get_check_constraints(
                "agent_runtime_add_receipts"
            )
        } == {
            "ck_agent_runtime_add_receipts_capability_versions",
            "ck_agent_runtime_add_receipts_profile_version",
            "ck_agent_runtime_add_receipts_runtime_generation",
        }

        alembic_command.downgrade(config, _PARENT_REVISION)
        assert "agent_runtime_add_receipts" not in sa.inspect(engine).get_table_names()

        alembic_command.upgrade(config, _RECEIPT_REVISION)
        assert "agent_runtime_add_receipts" in sa.inspect(engine).get_table_names()
