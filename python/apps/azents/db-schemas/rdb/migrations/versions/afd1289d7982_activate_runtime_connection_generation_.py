"""Activate Runtime connection-generation authority.

Revision ID: afd1289d7982
Revises: fa67b82b0b53
Create Date: 2026-09-07 22:28:44.464527
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "afd1289d7982"
down_revision: str | Sequence[str] | None = "fa67b82b0b53"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALLOCATOR_VERSION = 1
_LEGACY_CUTOVER_HIGH_WATER = 2**48 - 1
_MAX_CONNECTION_GENERATION = 2**63 - 1

_PROVIDER_TRIGGER = "trg_runtime_providers_connection_generation"
_PROVIDER_FUNCTION = "initialize_runtime_provider_connection_generation"
_RUNNER_TRIGGER = "trg_agent_runtimes_connection_generation"
_RUNNER_FUNCTION = "initialize_agent_runtime_connection_generation"


def upgrade() -> None:
    """Seed legacy subjects and install future-subject generation authority."""
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            LOCK TABLE runtime_providers, runtime_provider_connections,
                       agent_runtimes IN SHARE MODE
            """
        )
    )
    existing_state = bind.execute(
        sa.text(
            """
            SELECT
              (SELECT COUNT(*) FROM runtime_connection_generations),
              (SELECT COUNT(*) FROM runtime_connection_generation_cutovers)
            """
        )
    ).one()
    if any(int(value) != 0 for value in existing_state):
        raise RuntimeError(
            "Runtime connection generation authority is already initialized"
        )

    maxima = bind.execute(
        sa.text(
            """
            SELECT
              COALESCE((SELECT MAX(generation)
                        FROM runtime_provider_connections), 0),
              COALESCE((SELECT MAX(provider_generation)
                        FROM agent_runtimes), 0),
              COALESCE((SELECT MAX(runner_generation)
                        FROM agent_runtimes), 0)
            """
        )
    ).one()
    if any(int(value) > _MAX_CONNECTION_GENERATION for value in maxima):
        raise RuntimeError(
            "Runtime connection generation exceeds the exact numeric allocator domain"
        )

    bind.execute(
        sa.text(
            """
            INSERT INTO runtime_connection_generations (
              connection_kind,
              subject_id,
              high_water_generation,
              accepted_generation
            )
            SELECT
              'provider'::runtime_connection_authority_kind,
              provider.id,
              GREATEST(:legacy_high_water, COALESCE(MAX(connection.generation), 0)),
              COALESCE(MAX(connection.generation), 0)
            FROM runtime_providers AS provider
            LEFT JOIN runtime_provider_connections AS connection
              ON connection.provider_id = provider.id
            GROUP BY provider.id
            """
        ),
        {"legacy_high_water": _LEGACY_CUTOVER_HIGH_WATER},
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO runtime_connection_generations (
              connection_kind,
              subject_id,
              high_water_generation,
              accepted_generation
            )
            SELECT
              'runner'::runtime_connection_authority_kind,
              runtime.id,
              GREATEST(:legacy_high_water, runtime.runner_generation),
              runtime.runner_generation
            FROM agent_runtimes AS runtime
            """
        ),
        {"legacy_high_water": _LEGACY_CUTOVER_HIGH_WATER},
    )

    bind.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_PROVIDER_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
              INSERT INTO runtime_connection_generations (
                connection_kind,
                subject_id,
                high_water_generation,
                accepted_generation
              ) VALUES (
                'provider'::runtime_connection_authority_kind,
                NEW.id,
                0,
                0
              );
              RETURN NEW;
            END;
            $$
            """
        )
    )
    bind.execute(
        sa.text(
            f"""
            CREATE TRIGGER {_PROVIDER_TRIGGER}
            AFTER INSERT ON runtime_providers
            FOR EACH ROW
            EXECUTE FUNCTION {_PROVIDER_FUNCTION}()
            """
        )
    )
    bind.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_RUNNER_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
              INSERT INTO runtime_connection_generations (
                connection_kind,
                subject_id,
                high_water_generation,
                accepted_generation
              ) VALUES (
                'runner'::runtime_connection_authority_kind,
                NEW.id,
                0,
                0
              );
              RETURN NEW;
            END;
            $$
            """
        )
    )
    bind.execute(
        sa.text(
            f"""
            CREATE TRIGGER {_RUNNER_TRIGGER}
            AFTER INSERT ON agent_runtimes
            FOR EACH ROW
            EXECUTE FUNCTION {_RUNNER_FUNCTION}()
            """
        )
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO runtime_connection_generation_cutovers (
              allocator_version,
              cutover_at
            ) VALUES (:allocator_version, statement_timestamp())
            """
        ),
        {"allocator_version": _ALLOCATOR_VERSION},
    )


def downgrade() -> None:
    """Remove activation only when no new generation has been allocated."""
    bind = op.get_bind()
    changed = bind.scalar(
        sa.text(
            """
            SELECT EXISTS (
              SELECT 1
              FROM runtime_connection_generations
              WHERE NOT (
                (
                  high_water_generation = 0
                  AND accepted_generation = 0
                )
                OR (
                  high_water_generation = :legacy_high_water
                  AND accepted_generation <= :legacy_high_water
                )
              )
            )
            """
        ),
        {"legacy_high_water": _LEGACY_CUTOVER_HIGH_WATER},
    )
    if changed:
        raise RuntimeError(
            "irreversible: Runtime connection generation allocation has started"
        )

    bind.execute(sa.text(f"DROP TRIGGER {_RUNNER_TRIGGER} ON agent_runtimes"))
    bind.execute(sa.text(f"DROP FUNCTION {_RUNNER_FUNCTION}()"))
    bind.execute(sa.text(f"DROP TRIGGER {_PROVIDER_TRIGGER} ON runtime_providers"))
    bind.execute(sa.text(f"DROP FUNCTION {_PROVIDER_FUNCTION}()"))
    bind.execute(
        sa.text(
            """
            DELETE FROM runtime_connection_generation_cutovers
            WHERE allocator_version = :allocator_version
            """
        ),
        {"allocator_version": _ALLOCATOR_VERSION},
    )
    bind.execute(sa.text("DELETE FROM runtime_connection_generations"))
