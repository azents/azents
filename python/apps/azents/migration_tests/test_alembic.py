"""Operational baseline invariants for the Azents RDB revision graph."""

import pytest
import sqlalchemy as sa
import sqlalchemy.exc as sa_exc
from pytest_alembic import tests
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

from azents.rdb.models.base import RDBModel


def test_single_head_revision(alembic_runner: MigrationContext) -> None:
    """Require one deployable Alembic head."""
    tests.test_single_head_revision(alembic_runner)


def test_upgrade(alembic_runner: MigrationContext) -> None:
    """Require a complete base-to-head upgrade."""
    tests.test_upgrade(alembic_runner)


def test_model_definitions_match_ddl(alembic_runner: MigrationContext) -> None:
    """Require the migration head to match current SQLAlchemy metadata."""
    tests.test_model_definitions_match_ddl(alembic_runner)


def test_runtime_web_service_cutover_requires_drained_legacy_sessions(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Reject the destructive service cutover while a legacy route is active."""
    alembic_runner.migrate_up_to("097a97177350")
    with alembic_engine.begin() as connection:
        connection.execute(sa.text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            sa.text(
                """
                INSERT INTO runtime_web_session_routes (
                    runtime_id,
                    desired_generation,
                    runner_generation,
                    owner_replica_id,
                    owner_boot_id,
                    owner_address,
                    session_lease_id,
                    lease_generation,
                    join_nonce_hash,
                    protocol_fingerprint,
                    lease_expires_at
                )
                VALUES (
                    'legacy-runtime',
                    1,
                    1,
                    'legacy-control',
                    'legacy-boot',
                    'legacy-control:8032',
                    'legacy-session-lease',
                    1,
                    repeat('a', 64),
                    repeat('b', 64),
                    now() + interval '1 hour'
                )
                """
            )
        )

    with pytest.raises(
        sa_exc.DBAPIError,
        match="Runtime Web maintenance preflight found active legacy sessions",
    ):
        alembic_runner.migrate_up_to("head")

    with alembic_engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM runtime_web_session_routes"))
    alembic_runner.migrate_up_to("head")


def test_runtime_web_service_cutover_is_forward_only(
    alembic_runner: MigrationContext,
) -> None:
    """Reject restoration of deleted Session-scoped Runtime Web authority."""
    alembic_runner.migrate_up_to("head")
    with pytest.raises(
        RuntimeError,
        match="Runtime Web service-management cutover is irreversible and forward-only",
    ):
        alembic_runner.migrate_down_to("097a97177350")


def test_all_check_constraints_are_named(
    alembic_runner: MigrationContext,
) -> None:
    """Keep named CHECK constraint autogeneration safe to enable."""
    alembic_runner.migrate_up_to("head")
    check_constraints = [
        constraint
        for table in RDBModel.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    ]

    assert check_constraints
    assert all(constraint.name is not None for constraint in check_constraints)


def test_connection_generation_triggers(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Verify raw SQL triggers and functions not represented in model metadata."""
    alembic_runner.migrate_up_to("head")
    with alembic_engine.connect() as connection:
        rows = connection.execute(
            sa.text(
                """
                SELECT trigger.tgname, relation.relname, routine.proname,
                       trigger.tgtype, trigger.tgenabled, routine.prosrc
                FROM pg_trigger AS trigger
                JOIN pg_class AS relation ON relation.oid = trigger.tgrelid
                JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                JOIN pg_proc AS routine ON routine.oid = trigger.tgfoid
                WHERE namespace.nspname = 'public'
                  AND trigger.tgname IN (
                    'trg_agent_runtimes_connection_generation',
                    'trg_runtime_providers_connection_generation'
                  )
                """
            )
        ).all()

    expected = {
        "trg_agent_runtimes_connection_generation": (
            "agent_runtimes",
            "initialize_agent_runtime_connection_generation",
            "runner",
        ),
        "trg_runtime_providers_connection_generation": (
            "runtime_providers",
            "initialize_runtime_provider_connection_generation",
            "provider",
        ),
    }
    assert len(rows) == len(expected)
    for name, table, routine, trigger_type, enabled, body in rows:
        expected_table, expected_routine, kind = expected[name]
        assert (table, routine) == (expected_table, expected_routine)
        assert trigger_type == 5  # AFTER INSERT FOR EACH ROW
        assert enabled == "O"
        assert "INSERT INTO runtime_connection_generations" in body
        assert f"'{kind}'::runtime_connection_authority_kind" in body


def test_baseline_schema_and_seed_state(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Verify required singleton seeds and service cutover state."""
    alembic_runner.migrate_up_to("head")

    with alembic_engine.connect() as connection:
        file_lifecycle_settings = connection.execute(
            sa.text(
                """
                SELECT id, archived_session_retention_days,
                       updated_by_user_id, revision
                FROM system_file_lifecycle_settings
                """
            )
        ).one()
        assert file_lifecycle_settings == (1, 30, None, 1)

        runtime_cutover = connection.execute(
            sa.text(
                """
                SELECT allocator_version, cutover_at IS NOT NULL
                FROM runtime_connection_generation_cutovers
                """
            )
        ).one()
        assert runtime_cutover == (1, True)

        candidate_cutover = connection.execute(
            sa.text(
                """
                SELECT id, schema_version, new_format_written_at
                FROM model_candidate_chain_cutovers
                """
            )
        ).one()
        assert candidate_cutover == (1, 1, None)

        runtime_web_configuration = connection.execute(
            sa.text(
                """
                SELECT id, enabled, mode, fingerprint
                FROM runtime_web_auth_configuration
                """
            )
        ).one()
        assert runtime_web_configuration == (
            1,
            False,
            "separate_domain",
            "9d83c5f39577f63a9e9ce3eeef51751ed5798537fcea984a30dcdb21105d339d",
        )

        runtime_web_authority_tables = connection.execute(
            sa.text(
                """
                SELECT
                    to_regclass('public.runtime_web_services') IS NOT NULL,
                    to_regclass('public.runtime_web_endpoints') IS NULL,
                    to_regclass('public.runtime_web_requests') IS NULL,
                    to_regclass('public.runtime_web_cycles') IS NULL
                """
            )
        ).one()
        assert runtime_web_authority_tables == (True, True, True, True)
