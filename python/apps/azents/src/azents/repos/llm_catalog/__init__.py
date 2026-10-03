"""LLM catalog repositories."""

import datetime
from typing import Any, NamedTuple

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    LLMCatalogAttemptStatus,
    LLMCatalogEntryVisibility,
    LLMCatalogPurpose,
    LLMCatalogScope,
    LLMProvider,
)
from azents.core.llm_catalog import INTEGRATION_SCOPED_CATALOG_PROVIDERS
from azents.core.llm_catalog_sync import (
    CatalogProjectionVersion,
    CatalogSyncAttemptState,
    IntegrationCatalogSyncPolicyDecision,
    IntegrationCatalogSyncPolicyInput,
    IntegrationCatalogSyncTrigger,
    evaluate_integration_catalog_sync_policy,
)
from azents.rdb.models.llm_catalog import (
    RDBImageGenerationCatalogEntry,
    RDBLLMCatalog,
    RDBLLMCatalogEntry,
    RDBLLMCatalogSnapshot,
    RDBLLMCatalogSyncAttempt,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.model_metadata_source import RDBModelMetadataSource
from azents.rdb.models.workspace import RDBWorkspace

from .data import (
    CatalogProjectionProvenance,
    CatalogRetryPolicy,
    CatalogSyncAlreadyRunning,
    ImageGenerationCatalogEntry,
    ImageGenerationCatalogEntryCreate,
    ImageGenerationCatalogEntryList,
    ImageGenerationCatalogPublication,
    IntegrationCatalogSyncClaim,
    LLMCatalog,
    LLMCatalogEntry,
    LLMCatalogEntryCreate,
    LLMCatalogEntryList,
    LLMCatalogSnapshotCounts,
    LLMCatalogSyncAttempt,
)

_SYSTEM_CATALOG_ATTEMPT_LEASE = datetime.timedelta(minutes=5)


class CatalogEntryWithCatalog(NamedTuple):
    """One selectable catalog entry with its owning catalog."""

    catalog: LLMCatalog
    entry: LLMCatalogEntry


class ImageGenerationCatalogEntryWithCatalog(NamedTuple):
    """One selectable image entry with its owning catalog."""

    catalog: LLMCatalog
    entry: ImageGenerationCatalogEntry


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
            await session.execute(
                sa.select(RDBLLMCatalog.id)
                .where(RDBLLMCatalog.id == catalog_id)
                .with_for_update()
            )
            existing = await self.get_latest_attempt_by_catalog_id(
                session,
                catalog_id=catalog_id,
            )
            if (
                existing is not None
                and existing.status == LLMCatalogAttemptStatus.RUNNING
            ):
                if started_at < existing.started_at + _SYSTEM_CATALOG_ATTEMPT_LEASE:
                    return CatalogSyncAlreadyRunning(
                        catalog_id=catalog_id,
                        attempt_id=existing.id,
                    )
                await self.mark_attempt_failed(
                    session,
                    attempt_id=existing.id,
                    finished_at=started_at,
                    failure_code="SystemCatalogSyncRunningTimeout",
                    failure_message=(
                        "The previous system catalog refresh exceeded its running "
                        "lease."
                    ),
                    action_hint=("The abandoned refresh was reclaimed automatically."),
                    diagnostics={
                        "failure_category": "system_sync_lease_timeout",
                    },
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
                catalog_configuration_version=None,
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

    async def begin_integration_attempt(
        self,
        session: AsyncSession,
        *,
        catalog_id: str,
        workspace_id: str,
        source_key: str,
        started_at: datetime.datetime,
        trigger: IntegrationCatalogSyncTrigger,
        required_projection_version: CatalogProjectionVersion | None,
    ) -> IntegrationCatalogSyncClaim | IntegrationCatalogSyncPolicyDecision:
        """Atomically apply sync policy and create an integration attempt."""
        workspace_lock = await session.execute(
            sa.select(RDBWorkspace.id)
            .where(RDBWorkspace.id == workspace_id)
            .with_for_update()
        )
        if workspace_lock.scalar_one_or_none() is None:
            raise RuntimeError("Integration catalog workspace was not found.")
        catalog_result = await session.execute(
            sa.select(RDBLLMCatalog)
            .where(RDBLLMCatalog.id == catalog_id)
            .with_for_update()
        )
        catalog_rdb = catalog_result.scalar_one()
        catalog = self._build_catalog(catalog_rdb)
        if catalog.provider_integration_id is None:
            raise RuntimeError("Integration catalog is missing its integration.")
        integration_result = await session.execute(
            sa.select(RDBLLMProviderIntegration)
            .where(
                RDBLLMProviderIntegration.id == catalog.provider_integration_id,
                RDBLLMProviderIntegration.workspace_id == workspace_id,
            )
            .with_for_update()
        )
        integration = integration_result.scalar_one()
        latest_catalog_attempt = await self.get_latest_attempt(
            session,
            catalog=catalog,
        )
        latest_workspace_attempt = await (
            self.get_latest_integration_attempt_for_workspace
        )(
            session,
            workspace_id=workspace_id,
        )
        current_snapshot_created_at = await self.get_current_snapshot_created_at(
            session,
            catalog=catalog,
        )
        decision = evaluate_integration_catalog_sync_policy(
            IntegrationCatalogSyncPolicyInput(
                trigger=trigger,
                now=started_at,
                current_snapshot_created_at=current_snapshot_created_at,
                current_projection_version=(
                    await self.get_current_snapshot_projection_version(
                        session, catalog=catalog
                    )
                    if required_projection_version is not None
                    else None
                ),
                required_projection_version=required_projection_version,
                latest_catalog_attempt=self._policy_attempt(latest_catalog_attempt),
                latest_workspace_attempt=self._policy_attempt(latest_workspace_attempt),
            )
        )
        if not decision.allowed:
            return decision
        if decision.expired_running_attempt_id is not None:
            await self.mark_attempt_failed(
                session,
                attempt_id=decision.expired_running_attempt_id,
                finished_at=started_at,
                failure_code="CatalogSyncRunningTimeout",
                failure_message="The previous catalog sync exceeded its running lease.",
                action_hint="The stale attempt was recovered automatically.",
                diagnostics={
                    "failure_category": "sync_lease_timeout",
                    "automatic_retry_blocked": False,
                },
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
                diagnostics={
                    "trigger": trigger.value,
                    "catalog_purpose": catalog.purpose.value,
                },
                catalog_configuration_version=(
                    integration.catalog_configuration_version
                ),
            )
        )
        catalog_rdb.latest_attempt_id = attempt_id
        await session.flush()
        return IntegrationCatalogSyncClaim(
            attempt_id=attempt_id,
            expected_current_snapshot_id=catalog.current_snapshot_id,
            catalog_configuration_version=(integration.catalog_configuration_version),
        )

    async def lock_catalog_for_attempt_completion(
        self,
        session: AsyncSession,
        *,
        catalog_id: str,
    ) -> str | None:
        """Lock a catalog and return the attempt currently allowed to publish."""
        result = await session.execute(
            sa.select(RDBLLMCatalog.latest_attempt_id)
            .where(RDBLLMCatalog.id == catalog_id)
            .with_for_update()
        )
        return result.scalar_one()

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
        purpose: LLMCatalogPurpose,
    ) -> LLMCatalog:
        """Create or fetch an integration catalog."""
        result = await session.execute(
            insert(RDBLLMCatalog)
            .values(
                id=uuid7().hex,
                scope=LLMCatalogScope.INTEGRATION,
                provider=provider,
                provider_integration_id=integration_id,
                purpose=purpose,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    "provider_integration_id",
                    "purpose",
                ],
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
                    RDBLLMCatalog.purpose == purpose,
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
        purpose: LLMCatalogPurpose,
    ) -> LLMCatalog:
        """Create or fetch a system catalog."""
        result = await session.execute(
            insert(RDBLLMCatalog)
            .values(
                id=uuid7().hex,
                scope=LLMCatalogScope.SYSTEM,
                provider=provider,
                provider_integration_id=None,
                purpose=purpose,
            )
            .on_conflict_do_nothing(
                index_elements=["provider", "purpose"],
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
                    RDBLLMCatalog.purpose == purpose,
                )
            )
            rdb = existing.scalar_one()
        await session.flush()
        return self._build_catalog(rdb)

    async def create_candidate_snapshot(
        self,
        session: AsyncSession,
        *,
        catalog: LLMCatalog,
        entries: list[LLMCatalogEntryCreate],
        diagnostics: dict[str, Any] | None,
        provenance: CatalogProjectionProvenance,
        catalog_configuration_version: int | None,
    ) -> str:
        """Create or reuse one complete non-current replacement projection."""
        await session.execute(
            sa.select(RDBLLMCatalog.id)
            .where(RDBLLMCatalog.id == catalog.id)
            .with_for_update()
        )
        existing = await session.execute(
            sa.select(RDBLLMCatalogSnapshot.id).where(
                RDBLLMCatalogSnapshot.catalog_id == catalog.id,
                RDBLLMCatalogSnapshot.projection_fingerprint
                == provenance.projection_fingerprint,
                RDBLLMCatalogSnapshot.source_snapshot_id
                == provenance.source_snapshot_id,
            )
        )
        existing_id = existing.scalar_one_or_none()
        if existing_id is not None:
            return existing_id

        snapshot_id = uuid7().hex
        visible_count = sum(
            entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
            for entry in entries
        )
        session.add(
            RDBLLMCatalogSnapshot(
                id=snapshot_id,
                catalog_id=catalog.id,
                source_snapshot_id=(provenance.source_snapshot_id),
                projection_schema_version=provenance.projection_schema_version,
                runtime_profile_resolver_revision=(
                    provenance.runtime_profile_resolver_revision
                ),
                pydantic_ai_version=provenance.pydantic_ai_version,
                genai_prices_version=provenance.genai_prices_version,
                projection_fingerprint=provenance.projection_fingerprint,
                entry_count=len(entries),
                visible_count=visible_count,
                hidden_count=len(entries) - visible_count,
                diagnostics=diagnostics,
                catalog_configuration_version=catalog_configuration_version,
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
                    display_name=entry.display_name,
                    normalized_capabilities=entry.normalized_capabilities,
                    supported_execution_options=entry.supported_execution_options,
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
        await session.flush()
        return snapshot_id

    async def publish_candidate_snapshot(
        self,
        session: AsyncSession,
        *,
        catalog_id: str,
        candidate_snapshot_id: str,
        expected_current_snapshot_id: str | None,
        expected_catalog_configuration_version: int | None,
        expected_projection_fingerprint: str,
        expected_source_key: str | None = None,
        expected_source_snapshot_id: str | None = None,
        fence_latest_attempt: bool = False,
        expected_latest_attempt_id: str | None = None,
        reject_running_attempt: bool = False,
    ) -> str:
        """Publish one replacement candidate."""
        if (expected_source_key is None) != (expected_source_snapshot_id is None):
            raise ValueError("Source publication fencing requires key and snapshot.")
        if expected_source_key is not None:
            source_result = await session.execute(
                sa.select(RDBModelMetadataSource.current_snapshot_id)
                .where(RDBModelMetadataSource.source_key == expected_source_key)
                .with_for_update()
            )
            if source_result.scalar_one_or_none() != expected_source_snapshot_id:
                raise RuntimeError("The current model metadata source changed.")
        catalog_result = await session.execute(
            sa.select(RDBLLMCatalog)
            .where(RDBLLMCatalog.id == catalog_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        catalog = catalog_result.scalar_one()
        if catalog.current_snapshot_id != expected_current_snapshot_id:
            raise RuntimeError("The current catalog snapshot changed.")
        if (
            fence_latest_attempt
            and catalog.latest_attempt_id != expected_latest_attempt_id
        ):
            raise RuntimeError("The latest catalog sync attempt changed.")
        if reject_running_attempt and catalog.latest_attempt_id is not None:
            attempt_status_result = await session.execute(
                sa.select(RDBLLMCatalogSyncAttempt.status).where(
                    RDBLLMCatalogSyncAttempt.id == catalog.latest_attempt_id
                )
            )
            if (
                attempt_status_result.scalar_one_or_none()
                == LLMCatalogAttemptStatus.RUNNING
            ):
                raise RuntimeError("A provider catalog sync is running.")
        if (
            expected_catalog_configuration_version is not None
            and catalog.provider_integration_id is not None
        ):
            generation_result = await session.execute(
                sa.select(RDBLLMProviderIntegration.catalog_configuration_version)
                .where(RDBLLMProviderIntegration.id == catalog.provider_integration_id)
                .with_for_update()
            )
            if generation_result.scalar_one() != expected_catalog_configuration_version:
                raise RuntimeError(
                    "The integration catalog configuration generation changed."
                )
        candidate_result = await session.execute(
            sa.select(RDBLLMCatalogSnapshot).where(
                RDBLLMCatalogSnapshot.id == candidate_snapshot_id,
                RDBLLMCatalogSnapshot.catalog_id == catalog_id,
            )
        )
        candidate = candidate_result.scalar_one_or_none()
        if candidate is None:
            raise RuntimeError("The replacement catalog candidate was not found.")
        if (
            candidate.catalog_configuration_version
            != expected_catalog_configuration_version
            or candidate.projection_fingerprint != expected_projection_fingerprint
            or (
                expected_source_snapshot_id is not None
                and candidate.source_snapshot_id != expected_source_snapshot_id
            )
        ):
            raise RuntimeError("The replacement catalog candidate provenance changed.")
        previous_snapshot_id = catalog.current_snapshot_id
        catalog.current_snapshot_id = candidate_snapshot_id
        if (
            previous_snapshot_id is not None
            and previous_snapshot_id != candidate_snapshot_id
        ):
            await session.execute(
                sa.delete(RDBLLMCatalogSnapshot).where(
                    RDBLLMCatalogSnapshot.id == previous_snapshot_id
                )
            )
        await session.flush()
        return candidate_snapshot_id

    async def replace_current_image_generation_snapshot(
        self,
        session: AsyncSession,
        *,
        catalog: LLMCatalog,
        attempt_id: str,
        entries: list[ImageGenerationCatalogEntryCreate],
        diagnostics: dict[str, Any] | None,
    ) -> ImageGenerationCatalogPublication:
        """Publish an image catalog snapshot when attempt and config remain current."""
        if catalog.purpose != LLMCatalogPurpose.IMAGE_GENERATION:
            raise ValueError(
                "Image catalog publication requires image-generation purpose."
            )
        if catalog.provider_integration_id is None:
            raise ValueError("Image catalog publication requires an integration.")
        catalog_result = await session.execute(
            sa.select(RDBLLMCatalog)
            .where(RDBLLMCatalog.id == catalog.id)
            .with_for_update()
        )
        catalog_rdb = catalog_result.scalar_one()
        integration_result = await session.execute(
            sa.select(RDBLLMProviderIntegration)
            .where(RDBLLMProviderIntegration.id == catalog.provider_integration_id)
            .with_for_update()
        )
        integration = integration_result.scalar_one()
        attempt = await session.get(RDBLLMCatalogSyncAttempt, attempt_id)
        if attempt is None or attempt.catalog_id != catalog.id:
            raise ValueError("Image catalog attempt does not belong to the catalog.")
        if (
            catalog_rdb.latest_attempt_id != attempt_id
            or attempt.catalog_configuration_version
            != integration.catalog_configuration_version
        ):
            return ImageGenerationCatalogPublication(
                snapshot_id=None,
                superseding_attempt_id=catalog_rdb.latest_attempt_id,
                current_catalog_configuration_version=(
                    integration.catalog_configuration_version
                ),
            )

        snapshot_id = uuid7().hex
        visible_count = sum(
            entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
            for entry in entries
        )
        session.add(
            RDBLLMCatalogSnapshot(
                id=snapshot_id,
                catalog_id=catalog.id,
                source_snapshot_id=None,
                projection_schema_version=None,
                runtime_profile_resolver_revision=None,
                pydantic_ai_version=None,
                genai_prices_version=None,
                projection_fingerprint=None,
                entry_count=len(entries),
                visible_count=visible_count,
                hidden_count=len(entries) - visible_count,
                diagnostics=diagnostics,
                catalog_configuration_version=attempt.catalog_configuration_version,
            )
        )
        await session.flush()
        for entry in entries:
            session.add(
                RDBImageGenerationCatalogEntry(
                    id=uuid7().hex,
                    catalog_id=catalog.id,
                    snapshot_id=snapshot_id,
                    provider=entry.provider,
                    provider_model_identifier=entry.provider_model_identifier,
                    display_name=entry.display_name,
                    description=entry.description,
                    recommendation_rank=entry.recommendation_rank,
                    lifecycle_status=entry.lifecycle_status,
                    visibility_status=entry.visibility_status,
                    provider_integration_id=entry.provider_integration_id,
                    source_metadata=entry.source_metadata,
                    projection_metadata=entry.projection_metadata,
                    hidden_reason=entry.hidden_reason,
                )
            )
        previous_snapshot_id = catalog_rdb.current_snapshot_id
        catalog_rdb.current_snapshot_id = snapshot_id
        if previous_snapshot_id is not None:
            await session.execute(
                sa.delete(RDBLLMCatalogSnapshot).where(
                    RDBLLMCatalogSnapshot.id == previous_snapshot_id
                )
            )
        await session.flush()
        return ImageGenerationCatalogPublication(
            snapshot_id=snapshot_id,
            superseding_attempt_id=None,
            current_catalog_configuration_version=(
                integration.catalog_configuration_version
            ),
        )

    async def list_image_generation_entries_by_integration(
        self,
        session: AsyncSession,
        *,
        integration_id: str,
        workspace_id: str,
    ) -> ImageGenerationCatalogEntryList | None:
        """List current stored image-generation entries for an integration."""
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
            purpose=LLMCatalogPurpose.IMAGE_GENERATION,
        )
        if catalog is None:
            return None
        latest_attempt = await self.get_latest_attempt(session, catalog=catalog)
        if catalog.current_snapshot_id is None:
            return ImageGenerationCatalogEntryList(
                catalog=catalog,
                entries=[],
                total=0,
                current_snapshot_created_at=None,
                snapshot_catalog_configuration_version=None,
                current_integration_catalog_configuration_version=(
                    integration.catalog_configuration_version
                ),
                latest_attempt=latest_attempt,
            )
        snapshot_result = await session.execute(
            sa.select(RDBLLMCatalogSnapshot).where(
                RDBLLMCatalogSnapshot.id == catalog.current_snapshot_id
            )
        )
        snapshot = snapshot_result.scalar_one()
        filters = [
            RDBImageGenerationCatalogEntry.catalog_id == catalog.id,
            RDBImageGenerationCatalogEntry.snapshot_id == catalog.current_snapshot_id,
            RDBImageGenerationCatalogEntry.visibility_status
            == LLMCatalogEntryVisibility.SELECTABLE,
        ]
        result = await session.execute(
            sa.select(RDBImageGenerationCatalogEntry)
            .where(*filters)
            .order_by(
                RDBImageGenerationCatalogEntry.recommendation_rank.asc().nullslast(),
                RDBImageGenerationCatalogEntry.display_name.asc(),
                RDBImageGenerationCatalogEntry.provider_model_identifier.asc(),
            )
        )
        entries = [self._build_image_generation_entry(row) for row in result.scalars()]
        return ImageGenerationCatalogEntryList(
            catalog=catalog,
            entries=entries,
            total=len(entries),
            current_snapshot_created_at=snapshot.created_at,
            snapshot_catalog_configuration_version=(
                snapshot.catalog_configuration_version
            ),
            current_integration_catalog_configuration_version=(
                integration.catalog_configuration_version
            ),
            latest_attempt=latest_attempt,
        )

    async def get_selectable_image_generation_entry(
        self,
        session: AsyncSession,
        *,
        integration_id: str,
        workspace_id: str,
        model_identifier: str,
    ) -> ImageGenerationCatalogEntryWithCatalog | None:
        """Fetch one current-generation selectable image model entry."""
        page = await self.list_image_generation_entries_by_integration(
            session,
            integration_id=integration_id,
            workspace_id=workspace_id,
        )
        if (
            page is None
            or page.catalog.current_snapshot_id is None
            or page.snapshot_catalog_configuration_version
            != page.current_integration_catalog_configuration_version
        ):
            return None
        result = await session.execute(
            sa.select(RDBImageGenerationCatalogEntry).where(
                RDBImageGenerationCatalogEntry.catalog_id == page.catalog.id,
                RDBImageGenerationCatalogEntry.snapshot_id
                == page.catalog.current_snapshot_id,
                RDBImageGenerationCatalogEntry.visibility_status
                == LLMCatalogEntryVisibility.SELECTABLE,
                RDBImageGenerationCatalogEntry.provider_model_identifier
                == model_identifier,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return ImageGenerationCatalogEntryWithCatalog(
            catalog=page.catalog,
            entry=self._build_image_generation_entry(rdb),
        )

    async def list_entries_by_integration(
        self,
        session: AsyncSession,
        *,
        integration_id: str,
        workspace_id: str,
        purpose: LLMCatalogPurpose,
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
            purpose=purpose,
        )
        if (
            catalog is None
            and integration.provider not in INTEGRATION_SCOPED_CATALOG_PROVIDERS
        ):
            catalog = await self.get_system_catalog(
                session,
                provider=integration.provider,
                purpose=purpose,
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

    async def get_latest_integration_attempt_for_workspace(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
    ) -> LLMCatalogSyncAttempt | None:
        """Fetch the latest integration catalog attempt in a workspace."""
        result = await session.execute(
            sa.select(RDBLLMCatalogSyncAttempt)
            .join(
                RDBLLMCatalog,
                RDBLLMCatalog.id == RDBLLMCatalogSyncAttempt.catalog_id,
            )
            .join(
                RDBLLMProviderIntegration,
                RDBLLMProviderIntegration.id == RDBLLMCatalog.provider_integration_id,
            )
            .where(RDBLLMProviderIntegration.workspace_id == workspace_id)
            .order_by(RDBLLMCatalogSyncAttempt.started_at.desc())
            .limit(1)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build_attempt(rdb)

    async def get_current_snapshot_created_at(
        self,
        session: AsyncSession,
        *,
        catalog: LLMCatalog,
    ) -> datetime.datetime | None:
        """Fetch the creation time of the current catalog snapshot."""
        if catalog.current_snapshot_id is None:
            return None
        result = await session.execute(
            sa.select(RDBLLMCatalogSnapshot.created_at).where(
                RDBLLMCatalogSnapshot.id == catalog.current_snapshot_id
            )
        )
        return result.scalar_one_or_none()

    async def get_current_snapshot_projection_version(
        self,
        session: AsyncSession,
        *,
        catalog: LLMCatalog,
    ) -> CatalogProjectionVersion | None:
        """Read actual stored versions without introducing a runtime authority."""
        if catalog.current_snapshot_id is None:
            return None
        result = await session.execute(
            sa.select(RDBLLMCatalogSnapshot).where(
                RDBLLMCatalogSnapshot.id == catalog.current_snapshot_id
            )
        )
        snapshot = result.scalar_one_or_none()
        if snapshot is None:
            return None
        return CatalogProjectionVersion(
            schema_version=snapshot.projection_schema_version,
            resolver_revision=snapshot.runtime_profile_resolver_revision,
        )

    async def get_selectable_entry_by_integration_model(
        self,
        session: AsyncSession,
        *,
        integration_id: str,
        workspace_id: str,
        model_identifier: str,
        purpose: LLMCatalogPurpose,
    ) -> CatalogEntryWithCatalog | None:
        """Fetch one selectable current entry for an integration/model."""
        page = await self.list_entries_by_integration(
            session,
            integration_id=integration_id,
            workspace_id=workspace_id,
            purpose=purpose,
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
        return CatalogEntryWithCatalog(
            catalog=page.catalog,
            entry=self._build_entry(rdb),
        )

    async def get_system_catalog(
        self,
        session: AsyncSession,
        *,
        provider: LLMProvider,
        purpose: LLMCatalogPurpose,
    ) -> LLMCatalog | None:
        """Fetch a system catalog."""
        result = await session.execute(
            sa.select(RDBLLMCatalog).where(
                RDBLLMCatalog.scope == LLMCatalogScope.SYSTEM,
                RDBLLMCatalog.provider == provider,
                RDBLLMCatalog.purpose == purpose,
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
        purpose: LLMCatalogPurpose,
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
                RDBLLMCatalog.purpose == purpose,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build_catalog(rdb)

    def _policy_attempt(
        self,
        attempt: LLMCatalogSyncAttempt | None,
    ) -> CatalogSyncAttemptState | None:
        if attempt is None:
            return None
        retry_policy = CatalogRetryPolicy.from_diagnostics(attempt.diagnostics)
        return CatalogSyncAttemptState(
            id=attempt.id,
            status=attempt.status,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
            automatic_retry_blocked=retry_policy.automatic_retry_blocked,
        )

    def _build_catalog(self, rdb: RDBLLMCatalog) -> LLMCatalog:
        return LLMCatalog(
            id=rdb.id,
            scope=rdb.scope,
            provider=rdb.provider,
            purpose=rdb.purpose,
            provider_integration_id=rdb.provider_integration_id,
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
            display_name=rdb.display_name,
            normalized_capabilities=rdb.normalized_capabilities,
            supported_execution_options=rdb.supported_execution_options,
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

    def _build_image_generation_entry(
        self,
        rdb: RDBImageGenerationCatalogEntry,
    ) -> ImageGenerationCatalogEntry:
        return ImageGenerationCatalogEntry(
            id=rdb.id,
            catalog_id=rdb.catalog_id,
            snapshot_id=rdb.snapshot_id,
            provider=rdb.provider,
            provider_model_identifier=rdb.provider_model_identifier,
            display_name=rdb.display_name,
            description=rdb.description,
            recommendation_rank=rdb.recommendation_rank,
            lifecycle_status=rdb.lifecycle_status,
            visibility_status=rdb.visibility_status,
            provider_integration_id=rdb.provider_integration_id,
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
            catalog_configuration_version=rdb.catalog_configuration_version,
        )
