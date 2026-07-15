"""LLM catalog repositories."""

import datetime
from typing import Any

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    LLMCatalogAttemptStatus,
    LLMCatalogEntryVisibility,
    LLMCatalogLowererTarget,
    LLMCatalogScope,
    LLMProvider,
)
from azents.core.llm_catalog import INTEGRATION_SCOPED_CATALOG_PROVIDERS
from azents.rdb.models.llm_catalog import (
    RDBLiteLLMSourceSnapshot,
    RDBLLMCatalog,
    RDBLLMCatalogEntry,
    RDBLLMCatalogSnapshot,
    RDBLLMCatalogSyncAttempt,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration

from .data import (
    CatalogSyncAlreadyRunning,
    LiteLLMSourceSnapshot,
    LLMCatalog,
    LLMCatalogEntry,
    LLMCatalogEntryCreate,
    LLMCatalogEntryList,
    LLMCatalogSnapshotCounts,
    LLMCatalogSyncAttempt,
)


def _catalog_entry_freshness_rank() -> sa.ColumnElement[int]:
    """Build a SQL sort rank that prefers newer model identifiers."""
    metadata_rank = sa.cast(
        RDBLLMCatalogEntry.projection_metadata["freshness_rank"].astext,
        sa.Integer,
    )
    identifier = RDBLLMCatalogEntry.provider_model_identifier
    major = sa.cast(sa.func.substring(identifier, r"([0-9]+)"), sa.Integer)
    minor = sa.cast(
        sa.func.coalesce(
            sa.func.nullif(sa.func.substring(identifier, r"[0-9]+\\.([0-9]+)"), ""),
            "0",
        ),
        sa.Integer,
    )
    return sa.func.coalesce(metadata_rank, major * 1000 + minor, 0)


class LLMCatalogRepository:
    """Repository for projected model catalogs."""

    async def begin_attempt(
        self,
        session: AsyncSession,
        *,
        catalog_id: str | None,
        source_key: str,
        started_at: datetime.datetime,
    ) -> str | CatalogSyncAlreadyRunning:
        """Create a running sync attempt and mark it latest for a catalog."""
        if catalog_id is not None:
            existing = await self.get_latest_attempt_by_catalog_id(
                session,
                catalog_id=catalog_id,
            )
            if (
                existing is not None
                and existing.status == LLMCatalogAttemptStatus.RUNNING
            ):
                return CatalogSyncAlreadyRunning(
                    catalog_id=catalog_id,
                    attempt_id=existing.id,
                )
        attempt_id = uuid7().hex
        session.add(
            RDBLLMCatalogSyncAttempt(
                id=attempt_id,
                catalog_id=catalog_id,
                source_key=source_key,
                status=LLMCatalogAttemptStatus.RUNNING,
                started_at=started_at,
                fetched_count=0,
                matched_count=0,
                skipped_count=0,
                hidden_count=0,
            )
        )
        if catalog_id is not None:
            await session.execute(
                sa.update(RDBLLMCatalog)
                .where(RDBLLMCatalog.id == catalog_id)
                .values(latest_attempt_id=attempt_id)
            )
        await session.flush()
        return attempt_id

    async def mark_attempt_succeeded(
        self,
        session: AsyncSession,
        *,
        attempt_id: str,
        finished_at: datetime.datetime,
        produced_snapshot_id: str | None,
        fetched_count: int,
        matched_count: int,
        skipped_count: int,
        hidden_count: int,
        diagnostics: dict[str, Any] | None,
    ) -> None:
        """Mark a sync attempt as succeeded."""
        await session.execute(
            sa.update(RDBLLMCatalogSyncAttempt)
            .where(RDBLLMCatalogSyncAttempt.id == attempt_id)
            .values(
                status=LLMCatalogAttemptStatus.SUCCEEDED,
                finished_at=finished_at,
                produced_snapshot_id=produced_snapshot_id,
                fetched_count=fetched_count,
                matched_count=matched_count,
                skipped_count=skipped_count,
                hidden_count=hidden_count,
                diagnostics=diagnostics,
            )
        )
        await session.flush()

    async def mark_attempt_failed(
        self,
        session: AsyncSession,
        *,
        attempt_id: str,
        finished_at: datetime.datetime,
        failure_code: str,
        failure_message: str,
        action_hint: str | None,
        diagnostics: dict[str, Any] | None,
    ) -> None:
        """Mark a sync attempt as failed."""
        await session.execute(
            sa.update(RDBLLMCatalogSyncAttempt)
            .where(RDBLLMCatalogSyncAttempt.id == attempt_id)
            .values(
                status=LLMCatalogAttemptStatus.FAILED,
                finished_at=finished_at,
                failure_code=failure_code,
                failure_message=failure_message,
                action_hint=action_hint,
                diagnostics=diagnostics,
            )
        )
        await session.flush()

    async def ensure_integration_catalog(
        self,
        session: AsyncSession,
        *,
        integration_id: str,
        provider: LLMProvider,
        lowerer_target: LLMCatalogLowererTarget,
    ) -> LLMCatalog:
        """Create or fetch an integration catalog."""
        result = await session.execute(
            insert(RDBLLMCatalog)
            .values(
                id=uuid7().hex,
                scope=LLMCatalogScope.INTEGRATION,
                provider=provider,
                provider_integration_id=integration_id,
                lowerer_target=lowerer_target,
            )
            .on_conflict_do_nothing(
                index_elements=["provider_integration_id", "lowerer_target"],
                # Keep this predicate literal so PostgreSQL can infer the partial
                # unique index after psycopg prepares the repeated statement.
                index_where=sa.text("scope = 'integration'"),
            )
            .returning(RDBLLMCatalog)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            existing = await session.execute(
                sa.select(RDBLLMCatalog).where(
                    RDBLLMCatalog.provider_integration_id == integration_id,
                    RDBLLMCatalog.lowerer_target == lowerer_target,
                )
            )
            rdb = existing.scalar_one()
        await session.flush()
        return self._build_catalog(rdb)

    async def ensure_system_catalog(
        self,
        session: AsyncSession,
        *,
        provider: LLMProvider,
        lowerer_target: LLMCatalogLowererTarget,
    ) -> LLMCatalog:
        """Create or fetch a system catalog."""
        result = await session.execute(
            insert(RDBLLMCatalog)
            .values(
                id=uuid7().hex,
                scope=LLMCatalogScope.SYSTEM,
                provider=provider,
                provider_integration_id=None,
                lowerer_target=lowerer_target,
            )
            .on_conflict_do_nothing(
                index_elements=["provider", "lowerer_target"],
                # Keep this predicate literal so PostgreSQL can infer the partial
                # unique index after psycopg prepares the repeated statement.
                index_where=sa.text("scope = 'system'"),
            )
            .returning(RDBLLMCatalog)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            existing = await session.execute(
                sa.select(RDBLLMCatalog).where(
                    RDBLLMCatalog.scope == LLMCatalogScope.SYSTEM,
                    RDBLLMCatalog.provider == provider,
                    RDBLLMCatalog.lowerer_target == lowerer_target,
                )
            )
            rdb = existing.scalar_one()
        await session.flush()
        return self._build_catalog(rdb)

    async def replace_current_snapshot(
        self,
        session: AsyncSession,
        *,
        catalog: LLMCatalog,
        source_snapshot_id: str | None,
        entries: list[LLMCatalogEntryCreate],
        diagnostics: dict[str, Any] | None,
    ) -> str:
        """Replace the current successful snapshot for a catalog."""
        snapshot_id = uuid7().hex
        visible_count = sum(
            entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
            for entry in entries
        )
        session.add(
            RDBLLMCatalogSnapshot(
                id=snapshot_id,
                catalog_id=catalog.id,
                source_snapshot_id=source_snapshot_id,
                entry_count=len(entries),
                visible_count=visible_count,
                hidden_count=len(entries) - visible_count,
                diagnostics=diagnostics,
            )
        )
        await session.flush()
        for entry in entries:
            session.add(
                RDBLLMCatalogEntry(
                    id=uuid7().hex,
                    catalog_id=catalog.id,
                    snapshot_id=snapshot_id,
                    provider=entry.provider,
                    provider_model_identifier=entry.provider_model_identifier,
                    lowerer_target=entry.lowerer_target,
                    runtime_model_identifier=entry.runtime_model_identifier,
                    display_name=entry.display_name,
                    normalized_capabilities=entry.normalized_capabilities,
                    lifecycle_status=entry.lifecycle_status,
                    visibility_status=entry.visibility_status,
                    provider_integration_id=entry.provider_integration_id,
                    publisher=entry.publisher,
                    family=entry.family,
                    source_metadata=entry.source_metadata,
                    projection_metadata=entry.projection_metadata,
                    hidden_reason=entry.hidden_reason,
                )
            )
        await session.execute(
            sa.update(RDBLLMCatalog)
            .where(RDBLLMCatalog.id == catalog.id)
            .values(current_snapshot_id=snapshot_id)
        )
        if catalog.current_snapshot_id is not None:
            await session.execute(
                sa.delete(RDBLLMCatalogSnapshot).where(
                    RDBLLMCatalogSnapshot.id == catalog.current_snapshot_id
                )
            )
        await session.flush()
        return snapshot_id

    async def list_entries_by_integration(
        self,
        session: AsyncSession,
        *,
        integration_id: str,
        workspace_id: str,
        search: str | None,
        limit: int,
        offset: int,
    ) -> LLMCatalogEntryList | None:
        """List current selectable catalog entries for an integration."""
        integration_result = await session.execute(
            sa.select(RDBLLMProviderIntegration).where(
                RDBLLMProviderIntegration.id == integration_id,
                RDBLLMProviderIntegration.workspace_id == workspace_id,
            )
        )
        integration = integration_result.scalar_one_or_none()
        if integration is None:
            return None
        catalog = await self.get_by_integration(
            session,
            integration_id=integration_id,
            workspace_id=workspace_id,
        )
        if (
            catalog is None
            and integration.provider not in INTEGRATION_SCOPED_CATALOG_PROVIDERS
        ):
            catalog = await self.get_system_catalog(
                session,
                provider=integration.provider,
                lowerer_target=LLMCatalogLowererTarget.LITELLM,
            )
        if catalog is None:
            return None
        latest_attempt = await self.get_latest_attempt(session, catalog=catalog)
        if catalog.current_snapshot_id is None:
            return LLMCatalogEntryList(
                catalog=catalog,
                entries=[],
                total=0,
                current_snapshot_created_at=None,
                latest_attempt=latest_attempt,
            )
        filters = [
            RDBLLMCatalogEntry.catalog_id == catalog.id,
            RDBLLMCatalogEntry.snapshot_id == catalog.current_snapshot_id,
            RDBLLMCatalogEntry.visibility_status
            == LLMCatalogEntryVisibility.SELECTABLE,
        ]
        if search is not None:
            pattern = f"%{search}%"
            filters.append(
                sa.or_(
                    RDBLLMCatalogEntry.display_name.ilike(pattern),
                    RDBLLMCatalogEntry.provider_model_identifier.ilike(pattern),
                )
            )
        total_result = await session.execute(
            sa.select(sa.func.count()).select_from(RDBLLMCatalogEntry).where(*filters)
        )
        result = await session.execute(
            sa.select(RDBLLMCatalogEntry)
            .where(*filters)
            .order_by(
                _catalog_entry_freshness_rank().desc().nullslast(),
                RDBLLMCatalogEntry.display_name.asc(),
                RDBLLMCatalogEntry.provider_model_identifier.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        snapshot_result = await session.execute(
            sa.select(RDBLLMCatalogSnapshot.created_at).where(
                RDBLLMCatalogSnapshot.id == catalog.current_snapshot_id
            )
        )
        return LLMCatalogEntryList(
            catalog=catalog,
            entries=[self._build_entry(row) for row in result.scalars()],
            total=total_result.scalar_one(),
            current_snapshot_created_at=snapshot_result.scalar_one_or_none(),
            latest_attempt=latest_attempt,
        )

    async def get_latest_attempt(
        self,
        session: AsyncSession,
        *,
        catalog: LLMCatalog,
    ) -> LLMCatalogSyncAttempt | None:
        """Fetch latest sync attempt for a catalog."""
        if catalog.latest_attempt_id is None:
            return None
        result = await session.execute(
            sa.select(RDBLLMCatalogSyncAttempt).where(
                RDBLLMCatalogSyncAttempt.id == catalog.latest_attempt_id
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build_attempt(rdb)

    async def get_latest_attempt_by_catalog_id(
        self,
        session: AsyncSession,
        *,
        catalog_id: str,
    ) -> LLMCatalogSyncAttempt | None:
        """Fetch latest sync attempt for a catalog ID."""
        result = await session.execute(
            sa.select(RDBLLMCatalog.latest_attempt_id).where(
                RDBLLMCatalog.id == catalog_id
            )
        )
        attempt_id = result.scalar_one_or_none()
        if attempt_id is None:
            return None
        attempt_result = await session.execute(
            sa.select(RDBLLMCatalogSyncAttempt).where(
                RDBLLMCatalogSyncAttempt.id == attempt_id
            )
        )
        rdb = attempt_result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build_attempt(rdb)

    async def get_selectable_entry_by_integration_model(
        self,
        session: AsyncSession,
        *,
        integration_id: str,
        workspace_id: str,
        model_identifier: str,
    ) -> tuple[LLMCatalog, LLMCatalogEntry] | None:
        """Fetch one selectable current entry for an integration/model."""
        page = await self.list_entries_by_integration(
            session,
            integration_id=integration_id,
            workspace_id=workspace_id,
            search=None,
            limit=1,
            offset=0,
        )
        if page is None:
            return None
        result = await session.execute(
            sa.select(RDBLLMCatalogEntry).where(
                RDBLLMCatalogEntry.catalog_id == page.catalog.id,
                RDBLLMCatalogEntry.snapshot_id == page.catalog.current_snapshot_id,
                RDBLLMCatalogEntry.visibility_status
                == LLMCatalogEntryVisibility.SELECTABLE,
                RDBLLMCatalogEntry.provider_model_identifier == model_identifier,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return page.catalog, self._build_entry(rdb)

    async def get_system_catalog(
        self,
        session: AsyncSession,
        *,
        provider: LLMProvider,
        lowerer_target: LLMCatalogLowererTarget,
    ) -> LLMCatalog | None:
        """Fetch a system catalog."""
        result = await session.execute(
            sa.select(RDBLLMCatalog).where(
                RDBLLMCatalog.scope == LLMCatalogScope.SYSTEM,
                RDBLLMCatalog.provider == provider,
                RDBLLMCatalog.lowerer_target == lowerer_target,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build_catalog(rdb)

    async def get_current_snapshot_counts(
        self,
        session: AsyncSession,
        *,
        catalog: LLMCatalog,
    ) -> LLMCatalogSnapshotCounts | None:
        """Fetch current snapshot counts for a catalog."""
        if catalog.current_snapshot_id is None:
            return None
        result = await session.execute(
            sa.select(
                RDBLLMCatalogSnapshot.visible_count,
                RDBLLMCatalogSnapshot.hidden_count,
            ).where(RDBLLMCatalogSnapshot.id == catalog.current_snapshot_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return LLMCatalogSnapshotCounts(
            visible_count=row.visible_count,
            hidden_count=row.hidden_count,
        )

    async def get_by_integration(
        self,
        session: AsyncSession,
        *,
        integration_id: str,
        workspace_id: str,
    ) -> LLMCatalog | None:
        """Fetch an integration catalog in workspace scope."""
        result = await session.execute(
            sa.select(RDBLLMCatalog)
            .join(
                RDBLLMProviderIntegration,
                RDBLLMProviderIntegration.id == RDBLLMCatalog.provider_integration_id,
            )
            .where(
                RDBLLMCatalog.provider_integration_id == integration_id,
                RDBLLMProviderIntegration.workspace_id == workspace_id,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build_catalog(rdb)

    def _build_catalog(self, rdb: RDBLLMCatalog) -> LLMCatalog:
        return LLMCatalog(
            id=rdb.id,
            scope=rdb.scope,
            provider=rdb.provider,
            provider_integration_id=rdb.provider_integration_id,
            lowerer_target=rdb.lowerer_target,
            current_snapshot_id=rdb.current_snapshot_id,
            latest_attempt_id=rdb.latest_attempt_id,
        )

    def _build_entry(self, rdb: RDBLLMCatalogEntry) -> LLMCatalogEntry:
        return LLMCatalogEntry(
            id=rdb.id,
            catalog_id=rdb.catalog_id,
            snapshot_id=rdb.snapshot_id,
            provider=rdb.provider,
            provider_model_identifier=rdb.provider_model_identifier,
            lowerer_target=rdb.lowerer_target,
            runtime_model_identifier=rdb.runtime_model_identifier,
            display_name=rdb.display_name,
            normalized_capabilities=rdb.normalized_capabilities,
            lifecycle_status=rdb.lifecycle_status,
            visibility_status=rdb.visibility_status,
            provider_integration_id=rdb.provider_integration_id,
            publisher=rdb.publisher,
            family=rdb.family,
            source_metadata=rdb.source_metadata,
            projection_metadata=rdb.projection_metadata,
            hidden_reason=rdb.hidden_reason,
            created_at=rdb.created_at,
        )

    def _build_attempt(self, rdb: RDBLLMCatalogSyncAttempt) -> LLMCatalogSyncAttempt:
        return LLMCatalogSyncAttempt(
            id=rdb.id,
            catalog_id=rdb.catalog_id,
            source_key=rdb.source_key,
            status=rdb.status,
            started_at=rdb.started_at,
            finished_at=rdb.finished_at,
            produced_snapshot_id=rdb.produced_snapshot_id,
            failure_code=rdb.failure_code,
            failure_message=rdb.failure_message,
            action_hint=rdb.action_hint,
            fetched_count=rdb.fetched_count,
            matched_count=rdb.matched_count,
            skipped_count=rdb.skipped_count,
            hidden_count=rdb.hidden_count,
            diagnostics=rdb.diagnostics,
        )


class LiteLLMSourceSnapshotRepository:
    """Repository for LiteLLM source snapshots."""

    async def create_if_missing(
        self,
        session: AsyncSession,
        *,
        source_key: str,
        source_url: str | None,
        source_hash: str,
        model_count: int,
        litellm_version: str | None,
        loaded_source: str,
        payload: dict[str, Any],
    ) -> LiteLLMSourceSnapshot:
        """Create a source snapshot unless the same hash already exists."""
        result = await session.execute(
            insert(RDBLiteLLMSourceSnapshot)
            .values(
                id=uuid7().hex,
                source_key=source_key,
                source_url=source_url,
                source_hash=source_hash,
                model_count=model_count,
                litellm_version=litellm_version,
                loaded_source=loaded_source,
                payload=payload,
            )
            .on_conflict_do_nothing(index_elements=["source_hash"])
            .returning(RDBLiteLLMSourceSnapshot)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            rdb = await self.get_by_source_hash(session, source_hash)
        if rdb is None:
            raise RuntimeError("LiteLLM source snapshot upsert failed")
        await session.flush()
        return self._build(rdb)

    async def get_by_source_hash(
        self,
        session: AsyncSession,
        source_hash: str,
    ) -> RDBLiteLLMSourceSnapshot | None:
        """Fetch source snapshot by content hash."""
        result = await session.execute(
            sa.select(RDBLiteLLMSourceSnapshot).where(
                RDBLiteLLMSourceSnapshot.source_hash == source_hash
            )
        )
        return result.scalar_one_or_none()

    async def get_latest(
        self,
        session: AsyncSession,
    ) -> LiteLLMSourceSnapshot | None:
        """Fetch latest LiteLLM source snapshot."""
        result = await session.execute(
            sa.select(RDBLiteLLMSourceSnapshot)
            .order_by(RDBLiteLLMSourceSnapshot.created_at.desc())
            .limit(1)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    def _build(self, rdb: RDBLiteLLMSourceSnapshot) -> LiteLLMSourceSnapshot:
        return LiteLLMSourceSnapshot(
            id=rdb.id,
            source_key=rdb.source_key,
            source_url=rdb.source_url,
            source_hash=rdb.source_hash,
            model_count=rdb.model_count,
            litellm_version=rdb.litellm_version,
            loaded_source=rdb.loaded_source,
            payload=rdb.payload,
            created_at=rdb.created_at,
        )
