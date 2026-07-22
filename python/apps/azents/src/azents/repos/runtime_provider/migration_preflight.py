"""Read-only preflight for the Runtime Provider cutover migration."""

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.runtime_provider import RDBRuntimeProvider


@dataclass(frozen=True)
class LegacyProviderReference:
    """One legacy logical Provider reference and the owning row ID."""

    owner_id: str
    provider_logical_id: str


@dataclass(frozen=True)
class RuntimeProviderMigrationPreflightSnapshot:
    """Read-only legacy Provider state required for a safe cutover."""

    legacy_provider_logical_ids: tuple[str, ...]
    agent_references: tuple[LegacyProviderReference, ...]
    runtime_references: tuple[LegacyProviderReference, ...]
    runtime_ids_with_nonempty_provider_config: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeProviderMigrationPreflightFailure(Exception):
    """Legacy state violates the narrow Provider cutover preconditions."""

    code: str
    owner_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        Exception.__init__(
            self,
            f"Runtime Provider migration preflight failed: {self.code}",
        )


class RuntimeProviderMigrationPreflightRepository:
    """Read legacy Provider state without changing application data."""

    async def read(
        self,
        session: AsyncSession,
    ) -> RuntimeProviderMigrationPreflightSnapshot:
        """Return the complete legacy state used by cutover validation."""
        provider_rows = await session.execute(
            sa.select(RDBRuntimeProvider.provider_id).order_by(
                RDBRuntimeProvider.provider_id
            )
        )
        agent_rows = await session.execute(
            sa.select(RDBAgent.id, RDBAgent.runtime_provider_id)
            .where(RDBAgent.runtime_provider_id.is_not(None))
            .order_by(RDBAgent.id)
        )
        runtime_rows = await session.execute(
            sa.select(
                RDBAgentRuntime.id,
                RDBAgentRuntime.runtime_provider_id,
                RDBAgentRuntime.provider_config,
            ).order_by(RDBAgentRuntime.id)
        )

        nonempty_provider_config_ids: list[str] = []
        agent_references: list[LegacyProviderReference] = []
        for agent_id, provider_logical_id in agent_rows.tuples():
            if provider_logical_id is None:
                continue
            agent_references.append(
                LegacyProviderReference(
                    owner_id=agent_id,
                    provider_logical_id=provider_logical_id,
                )
            )
        runtime_references: list[LegacyProviderReference] = []
        for runtime_id, provider_logical_id, provider_config in runtime_rows.tuples():
            if provider_logical_id is not None:
                runtime_references.append(
                    LegacyProviderReference(
                        owner_id=runtime_id,
                        provider_logical_id=provider_logical_id,
                    )
                )
            if provider_config:
                nonempty_provider_config_ids.append(runtime_id)

        return RuntimeProviderMigrationPreflightSnapshot(
            legacy_provider_logical_ids=tuple(provider_rows.scalars()),
            agent_references=tuple(agent_references),
            runtime_references=tuple(runtime_references),
            runtime_ids_with_nonempty_provider_config=tuple(
                nonempty_provider_config_ids
            ),
        )


def validate_runtime_provider_migration_preflight(
    snapshot: RuntimeProviderMigrationPreflightSnapshot,
    *,
    expected_legacy_provider_logical_id: str,
) -> None:
    """Reject legacy state that cannot be safely backfilled without guessing."""
    if snapshot.legacy_provider_logical_ids:
        raise RuntimeProviderMigrationPreflightFailure(
            code="legacy_runtime_provider_rows_present",
            owner_ids=snapshot.legacy_provider_logical_ids,
        )
    unexpected_agent_ids = tuple(
        reference.owner_id
        for reference in snapshot.agent_references
        if reference.provider_logical_id != expected_legacy_provider_logical_id
    )
    if unexpected_agent_ids:
        raise RuntimeProviderMigrationPreflightFailure(
            code="unexpected_agent_provider_id",
            owner_ids=unexpected_agent_ids,
        )
    unexpected_runtime_ids = tuple(
        reference.owner_id
        for reference in snapshot.runtime_references
        if reference.provider_logical_id != expected_legacy_provider_logical_id
    )
    if unexpected_runtime_ids:
        raise RuntimeProviderMigrationPreflightFailure(
            code="unexpected_runtime_provider_id",
            owner_ids=unexpected_runtime_ids,
        )
    if snapshot.runtime_ids_with_nonempty_provider_config:
        raise RuntimeProviderMigrationPreflightFailure(
            code="legacy_runtime_provider_config_present",
            owner_ids=snapshot.runtime_ids_with_nonempty_provider_config,
        )
