"""Operational baseline invariants for the Azents RDB revision graph."""

import hashlib
import json

import pytest
import sqlalchemy as sa
import sqlalchemy.exc as sa_exc
from pytest_alembic import tests
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

from azents.rdb.models.base import RDBModel

_EXPECTED_PUBLIC_SCHEMA_FINGERPRINT = (
    "68b1355da00444b079b55fc6a775a323720ecd193ecdb80b1c65f12c1a13d759"
)


def _public_schema_fingerprint(connection: sa.Connection) -> str:
    """Return a stable fingerprint of the PostgreSQL public schema catalog."""
    rows = connection.execute(
        sa.text(
            r"""
            WITH entries AS (
                SELECT
                    'enum'::text AS category,
                    format(
                        '%I.%I[%s]',
                        namespace.nspname,
                        type.typname,
                        row_number() OVER (
                            PARTITION BY type.oid ORDER BY enum.enumsortorder
                        )
                    ) AS identity,
                    enum.enumlabel::text AS definition
                FROM pg_type AS type
                JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace
                JOIN pg_enum AS enum ON enum.enumtypid = type.oid
                WHERE namespace.nspname = 'public'

                UNION ALL

                SELECT
                    'relation',
                    format('%I.%I', namespace.nspname, class.relname),
                    class.relkind::text
                FROM pg_class AS class
                JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
                WHERE namespace.nspname = 'public'
                  AND class.relkind IN ('r', 'p', 'v', 'm', 'S')
                  AND class.relname <> 'alembic_version'

                UNION ALL

                SELECT
                    'column',
                    format('%I.%I.%I', namespace.nspname, class.relname,
                           attribute.attname),
                    concat_ws(
                        '|',
                        format_type(attribute.atttypid, attribute.atttypmod),
                        attribute.attnotnull::text,
                        COALESCE(pg_get_expr(default_value.adbin,
                                             default_value.adrelid), ''),
                        attribute.attidentity::text,
                        attribute.attgenerated::text
                    )
                FROM pg_attribute AS attribute
                JOIN pg_class AS class ON class.oid = attribute.attrelid
                JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
                LEFT JOIN pg_attrdef AS default_value
                  ON default_value.adrelid = attribute.attrelid
                 AND default_value.adnum = attribute.attnum
                WHERE namespace.nspname = 'public'
                  AND class.relkind IN ('r', 'p', 'v', 'm')
                  AND class.relname <> 'alembic_version'
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped

                UNION ALL

                SELECT
                    'constraint',
                    format('%I.%I.%I', namespace.nspname, class.relname,
                           catalog_constraint.conname),
                    pg_get_constraintdef(catalog_constraint.oid, true)
                FROM pg_constraint AS catalog_constraint
                JOIN pg_class AS class ON class.oid = catalog_constraint.conrelid
                JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
                WHERE namespace.nspname = 'public'
                  AND class.relname <> 'alembic_version'
                  AND catalog_constraint.contype <> 'n'

                UNION ALL

                SELECT
                    'index',
                    format('%I.%I', schemaname, indexname),
                    indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename <> 'alembic_version'

                UNION ALL

                SELECT
                    'function',
                    format('%I.%I(%s)', namespace.nspname, procedure.proname,
                           pg_get_function_identity_arguments(procedure.oid)),
                    pg_get_functiondef(procedure.oid)
                FROM pg_proc AS procedure
                JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
                WHERE namespace.nspname = 'public'

                UNION ALL

                SELECT
                    'trigger',
                    format('%I.%I.%I', namespace.nspname, class.relname,
                           trigger.tgname),
                    pg_get_triggerdef(trigger.oid, true)
                FROM pg_trigger AS trigger
                JOIN pg_class AS class ON class.oid = trigger.tgrelid
                JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
                WHERE namespace.nspname = 'public'
                  AND NOT trigger.tgisinternal

                UNION ALL

                SELECT
                    'sequence',
                    format('%I.%I', namespace.nspname, class.relname),
                    concat_ws(
                        '|',
                        format_type(sequence.seqtypid, NULL),
                        sequence.seqstart::text,
                        sequence.seqincrement::text,
                        sequence.seqmax::text,
                        sequence.seqmin::text,
                        sequence.seqcache::text,
                        sequence.seqcycle::text
                    )
                FROM pg_sequence AS sequence
                JOIN pg_class AS class ON class.oid = sequence.seqrelid
                JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
                WHERE namespace.nspname = 'public'

                UNION ALL

                SELECT
                    'policy',
                    format('%I.%I.%I', schemaname, tablename, policyname),
                    concat_ws(
                        '|',
                        permissive,
                        array_to_string(roles, ','),
                        cmd,
                        COALESCE(qual, ''),
                        COALESCE(with_check, '')
                    )
                FROM pg_policies
                WHERE schemaname = 'public'
            )
            SELECT category, identity, definition
            FROM entries
            ORDER BY category, identity, definition
            """
        )
    ).tuples()
    payload = json.dumps(
        [tuple(row) for row in rows], ensure_ascii=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


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


def test_baseline_schema_and_seed_state(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Pin the production schema catalog and required singleton seeds."""
    alembic_runner.migrate_up_to("head")

    with alembic_engine.connect() as connection:
        assert _public_schema_fingerprint(connection) == (
            _EXPECTED_PUBLIC_SCHEMA_FINGERPRINT
        )
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
