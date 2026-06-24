"""RuntimeProvider repository."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.runtime_provider import RDBRuntimeProvider

from .data import RuntimeProvider, RuntimeProviderCreate


class RuntimeProviderRepository:
    """Runtime Provider CRUD repository."""

    async def create(
        self,
        session: AsyncSession,
        create: RuntimeProviderCreate,
    ) -> RuntimeProvider:
        """Create Runtime Provider row."""
        rdb = RDBRuntimeProvider(
            provider_id=create.provider_id,
            scope=create.scope,
            workspace_id=create.workspace_id,
            kind=create.kind,
            display_name=create.display_name,
            enabled=create.enabled,
            capabilities=create.capabilities,
            config_schema=create.config_schema,
            metadata_=create.metadata,
        )
        session.add(rdb)
        await session.flush()
        return self._build(rdb)

    async def get_by_provider_id(
        self,
        session: AsyncSession,
        provider_id: str,
    ) -> RuntimeProvider | None:
        """Fetch Runtime Provider by provider_id."""
        result = await session.execute(
            sa.select(RDBRuntimeProvider).where(
                RDBRuntimeProvider.provider_id == provider_id
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def list_available(
        self,
        session: AsyncSession,
        *,
        workspace_id: str | None = None,
        include_disabled: bool = False,
    ) -> list[RuntimeProvider]:
        """Fetch available Runtime Provider list."""
        stmt = sa.select(RDBRuntimeProvider)
        if workspace_id is not None:
            stmt = stmt.where(
                sa.or_(
                    RDBRuntimeProvider.workspace_id == workspace_id,
                    RDBRuntimeProvider.workspace_id.is_(None),
                )
            )
        if not include_disabled:
            stmt = stmt.where(RDBRuntimeProvider.enabled.is_(True))
        stmt = stmt.order_by(RDBRuntimeProvider.provider_id)
        result = await session.execute(stmt)
        return [self._build(rdb) for rdb in result.scalars()]

    async def set_enabled(
        self,
        session: AsyncSession,
        provider_id: str,
        enabled: bool,
    ) -> None:
        """Update Runtime Provider enabled value."""
        await session.execute(
            sa.update(RDBRuntimeProvider)
            .where(RDBRuntimeProvider.provider_id == provider_id)
            .values(enabled=enabled)
        )
        await session.flush()

    def _build(self, rdb: RDBRuntimeProvider) -> RuntimeProvider:
        """Convert RDB model to domain model."""
        return RuntimeProvider(
            id=rdb.id,
            provider_id=rdb.provider_id,
            scope=rdb.scope,
            workspace_id=rdb.workspace_id,
            kind=rdb.kind,
            display_name=rdb.display_name,
            enabled=rdb.enabled,
            capabilities=rdb.capabilities,
            config_schema=rdb.config_schema,
            metadata=rdb.metadata_,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
