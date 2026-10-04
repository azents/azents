"""Current catalog rows, coherent selectors and operational ownership."""

import dataclasses
import datetime
from collections.abc import Sequence
from typing import Any, NamedTuple

import sqlalchemy as sa
from azcommon.uuid import uuid7
from pydantic import TypeAdapter
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.active_model_capabilities import ConfiguredModelIdentity
from azents.core.enums import (
    LLMCatalogAttemptStatus,
    LLMCatalogEntryVisibility,
    LLMCatalogPurpose,
    LLMCatalogScope,
    LLMProvider,
)
from azents.core.llm_catalog import (
    INTEGRATION_SCOPED_CATALOG_PROVIDERS,
    ModelCapabilities,
)
from azents.core.llm_catalog_sync import (
    CatalogProjectionVersion,
    CatalogSyncState,
    IntegrationCatalogSyncPolicyDecision,
    IntegrationCatalogSyncPolicyInput,
    IntegrationCatalogSyncTrigger,
    evaluate_integration_catalog_sync_policy,
)
from azents.core.model_capability_projection import CAPABILITY_PROJECTION_REVISION
from azents.core.model_pricing import ModelPricingDefinition
from azents.rdb.models.llm_catalog import (
    RDBImageGenerationCatalogEntry,
    RDBLLMCatalog,
    RDBLLMCatalogEntry,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.workspace import RDBWorkspace
from azents.repos.llm_catalog.data import (
    CatalogRetryPolicy,
    CatalogSyncAlreadyRunning,
    ImageGenerationCatalogEntry,
    ImageGenerationCatalogEntryCreate,
    ImageGenerationCatalogEntryList,
    IntegrationCatalogSyncClaim,
    LLMCatalog,
    LLMCatalogCounts,
    LLMCatalogEntry,
    LLMCatalogEntryCreate,
    LLMCatalogEntryList,
    LLMCatalogSyncStatus,
)
from azents.repos.model_catalog_sync_state import (
    current_sync_status,
    fail_sync,
    start_sync,
    succeed_sync,
)

_SYSTEM_CATALOG_SYNC_LEASE = datetime.timedelta(minutes=5)
_ROW_BATCH_SIZE = 250


class CatalogEntryWithCatalog(NamedTuple):
    """One current selectable model and its coherent owner state."""

    catalog: LLMCatalog
    entry: LLMCatalogEntry


class ImageGenerationCatalogEntryWithCatalog(NamedTuple):
    """One current image model and its coherent owner state."""

    catalog: LLMCatalog
    entry: ImageGenerationCatalogEntry


def _catalog_entry_freshness_rank() -> sa.ColumnElement[int]:
    metadata_rank = sa.cast(
        RDBLLMCatalogEntry.projection_metadata["freshness_rank"].astext, sa.Integer
    )
    identifier = RDBLLMCatalogEntry.provider_model_identifier
    major = sa.cast(sa.func.substring(identifier, r"([0-9]+)"), sa.Integer)
    minor = sa.cast(
        sa.func.coalesce(
            sa.func.nullif(sa.func.substring(identifier, r"[0-9]+\\.([0-9]+)"), ""), "0"
        ),
        sa.Integer,
    )
    return sa.func.coalesce(metadata_rank, major * 1000 + minor, 0)


class LLMCatalogRepository:
    """Repository for stable owners and atomically replaced current model sets."""

    async def lock_catalog(
        self, session: AsyncSession, *, catalog_id: str, shared: bool = False
    ) -> RDBLLMCatalog:
        result = await session.execute(
            sa.select(RDBLLMCatalog)
            .where(RDBLLMCatalog.id == catalog_id)
            .with_for_update(read=shared)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one()

    async def lock_integration(
        self,
        session: AsyncSession,
        *,
        integration_id: str,
        workspace_id: str | None,
        shared: bool = False,
    ) -> RDBLLMProviderIntegration | None:
        statement = sa.select(RDBLLMProviderIntegration).where(
            RDBLLMProviderIntegration.id == integration_id
        )
        if workspace_id is not None:
            statement = statement.where(
                RDBLLMProviderIntegration.workspace_id == workspace_id
            )
        result = await session.execute(
            statement.with_for_update(read=shared).execution_options(
                populate_existing=True
            )
        )
        return result.scalar_one_or_none()

    async def begin_sync(
        self, session: AsyncSession, *, catalog_id: str, started_at: datetime.datetime
    ) -> str | CatalogSyncAlreadyRunning:
        """Claim system work under the stable owner, preserving the existing lease."""
        owner = await self.lock_catalog(session, catalog_id=catalog_id)
        existing = current_sync_status(owner)
        if (
            existing is not None
            and existing.status == LLMCatalogAttemptStatus.RUNNING
            and started_at < existing.started_at + _SYSTEM_CATALOG_SYNC_LEASE
        ):
            if existing.work_token is None:
                raise ValueError(
                    "Running catalog synchronization is missing ownership."
                )
            return CatalogSyncAlreadyRunning(
                catalog_id=catalog_id, work_token=existing.work_token
            )
        token = start_sync(
            owner, work_token=None, started_at=started_at, diagnostics=None
        )
        await session.flush()
        return token

    async def begin_integration_sync(
        self,
        session: AsyncSession,
        *,
        catalog_id: str,
        workspace_id: str,
        started_at: datetime.datetime,
        trigger: IntegrationCatalogSyncTrigger,
        required_projection_version: CatalogProjectionVersion | None,
    ) -> IntegrationCatalogSyncClaim | IntegrationCatalogSyncPolicyDecision:
        """Serialize workspace policy after locking integration authority."""
        initial = await session.get(RDBLLMCatalog, catalog_id)
        if initial is None or initial.provider_integration_id is None:
            raise ValueError("Integration catalog was not found.")
        integration = await self.lock_integration(
            session,
            integration_id=initial.provider_integration_id,
            workspace_id=workspace_id,
        )
        if integration is None:
            raise ValueError("Integration catalog workspace was not found.")
        workspace_result = await session.execute(
            sa.select(RDBWorkspace.id)
            .where(RDBWorkspace.id == workspace_id)
            .with_for_update()
        )
        if workspace_result.scalar_one_or_none() is None:
            raise ValueError("Integration catalog workspace was not found.")
        owner = await self.lock_catalog(session, catalog_id=catalog_id)
        latest = current_sync_status(owner)
        workspace_latest = await self.get_latest_integration_sync_for_workspace(
            session, workspace_id=workspace_id
        )
        decision = evaluate_integration_catalog_sync_policy(
            IntegrationCatalogSyncPolicyInput(
                trigger=trigger,
                now=started_at,
                last_success_at=owner.last_success_at,
                current_projection_version=(
                    self.projection_version(owner)
                    if required_projection_version is not None
                    else None
                ),
                required_projection_version=required_projection_version,
                latest_catalog_sync=self.policy_sync(latest),
                latest_workspace_sync=self.policy_sync(workspace_latest),
            )
        )
        if not decision.allowed:
            return decision
        token = start_sync(
            owner,
            work_token=None,
            started_at=started_at,
            diagnostics={
                "trigger": trigger.value,
                "catalog_purpose": owner.purpose.value,
            },
        )
        await session.flush()
        return IntegrationCatalogSyncClaim(
            work_token=token,
            catalog_configuration_version=integration.catalog_configuration_version,
        )

    @staticmethod
    def projection_version(
        catalog: LLMCatalog | RDBLLMCatalog,
    ) -> CatalogProjectionVersion | None:
        """Decode compatibility facts from current successful owner metadata."""
        if catalog.diagnostics is None:
            return None
        payload = catalog.diagnostics.get("projection_version")
        if payload is None:
            return None
        return TypeAdapter(CatalogProjectionVersion).validate_python(payload)

    async def complete_sync(
        self,
        session: AsyncSession,
        *,
        catalog_id: str,
        work_token: str,
        finished_at: datetime.datetime,
        fetched_count: int,
        matched_count: int,
        skipped_count: int,
        hidden_count: int,
        diagnostics: dict[str, Any] | None,
    ) -> None:
        owner = await self.lock_catalog(session, catalog_id=catalog_id)
        succeed_sync(
            owner,
            work_token=work_token,
            finished_at=finished_at,
            fetched_count=fetched_count,
            matched_count=matched_count,
            skipped_count=skipped_count,
            hidden_count=hidden_count,
            diagnostics=diagnostics,
        )
        await session.flush()

    async def fail_sync(
        self,
        session: AsyncSession,
        *,
        catalog_id: str,
        work_token: str,
        finished_at: datetime.datetime,
        failure_code: str,
        failure_message: str,
        action_hint: str | None,
        diagnostics: dict[str, Any] | None,
    ) -> bool:
        owner = await self.lock_catalog(session, catalog_id=catalog_id)
        changed = fail_sync(
            owner,
            work_token=work_token,
            finished_at=finished_at,
            failure_code=failure_code,
            failure_message=failure_message,
            action_hint=action_hint,
            diagnostics=diagnostics,
        )
        await session.flush()
        return changed

    async def ensure_integration_catalog(
        self,
        session: AsyncSession,
        *,
        integration_id: str,
        provider: LLMProvider,
        purpose: LLMCatalogPurpose,
    ) -> LLMCatalog:
        result = await session.execute(
            insert(RDBLLMCatalog)
            .values(
                id=uuid7().hex,
                scope=LLMCatalogScope.INTEGRATION,
                provider=provider,
                provider_integration_id=integration_id,
                purpose=purpose,
                image_usable=False
                if purpose == LLMCatalogPurpose.IMAGE_GENERATION
                else None,
            )
            .on_conflict_do_nothing(
                index_elements=["provider_integration_id", "purpose"],
                index_where=sa.text("scope = 'integration'"),
            )
            .returning(RDBLLMCatalog)
        )
        owner = result.scalar_one_or_none()
        if owner is None:
            existing = await session.execute(
                sa.select(RDBLLMCatalog).where(
                    RDBLLMCatalog.provider_integration_id == integration_id,
                    RDBLLMCatalog.purpose == purpose,
                )
            )
            owner = existing.scalar_one()
        return self.build_catalog(owner)

    async def ensure_system_catalog(
        self,
        session: AsyncSession,
        *,
        provider: LLMProvider,
        purpose: LLMCatalogPurpose,
    ) -> LLMCatalog:
        result = await session.execute(
            insert(RDBLLMCatalog)
            .values(
                id=uuid7().hex,
                scope=LLMCatalogScope.SYSTEM,
                provider=provider,
                provider_integration_id=None,
                purpose=purpose,
                image_usable=False
                if purpose == LLMCatalogPurpose.IMAGE_GENERATION
                else None,
            )
            .on_conflict_do_nothing(
                index_elements=["provider", "purpose"],
                index_where=sa.text("scope = 'system'"),
            )
            .returning(RDBLLMCatalog)
        )
        owner = result.scalar_one_or_none()
        if owner is None:
            existing = await session.execute(
                sa.select(RDBLLMCatalog).where(
                    RDBLLMCatalog.scope == LLMCatalogScope.SYSTEM,
                    RDBLLMCatalog.provider == provider,
                    RDBLLMCatalog.purpose == purpose,
                )
            )
            owner = existing.scalar_one()
        return self.build_catalog(owner)

    async def replace_current_entries(
        self,
        session: AsyncSession,
        *,
        owner: RDBLLMCatalog,
        entries: list[LLMCatalogEntryCreate],
        diagnostics: dict[str, Any] | None,
        finished_at: datetime.datetime,
    ) -> None:
        """Overwrite current exact rows, retaining row IDs and deleting removed keys."""
        if owner.purpose != LLMCatalogPurpose.CONVERSATION:
            raise ValueError("Conversation publication requires a conversation owner.")
        self._validate_entry_scope(owner, entries)
        self._validate_conversation_capabilities(entries)
        identifiers = {entry.provider_model_identifier for entry in entries}
        existing_result = await session.execute(
            sa.select(RDBLLMCatalogEntry.provider_model_identifier)
            .where(RDBLLMCatalogEntry.catalog_id == owner.id)
            .with_for_update()
        )
        obsolete = sorted(set(existing_result.scalars()) - identifiers)
        for start in range(0, len(entries), _ROW_BATCH_SIZE):
            values = []
            for entry in entries[start : start + _ROW_BATCH_SIZE]:
                value = dataclasses.asdict(entry)
                value["pricing"] = entry.pricing.model_dump(mode="json")
                values.append(
                    {
                        "id": uuid7().hex,
                        "catalog_id": owner.id,
                        "updated_at": finished_at,
                        **value,
                    }
                )
            statement = insert(RDBLLMCatalogEntry).values(values)
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=["catalog_id", "provider_model_identifier"],
                    set_={
                        column.name: statement.excluded[column.name]
                        for column in RDBLLMCatalogEntry.__table__.columns
                        if column.name
                        not in {
                            "id",
                            "catalog_id",
                            "provider_model_identifier",
                            "created_at",
                        }
                    },
                )
            )
        for start in range(0, len(obsolete), _ROW_BATCH_SIZE):
            await session.execute(
                sa.delete(RDBLLMCatalogEntry).where(
                    RDBLLMCatalogEntry.catalog_id == owner.id,
                    RDBLLMCatalogEntry.provider_model_identifier.in_(
                        obsolete[start : start + _ROW_BATCH_SIZE]
                    ),
                )
            )
        self._record_success(
            owner, entries=entries, diagnostics=diagnostics, finished_at=finished_at
        )
        await session.flush()

    async def replace_current_image_entries(
        self,
        session: AsyncSession,
        *,
        owner: RDBLLMCatalog,
        entries: list[ImageGenerationCatalogEntryCreate],
        diagnostics: dict[str, Any] | None,
        finished_at: datetime.datetime,
    ) -> None:
        """Replace only current reviewed image entries; caller rechecks credentials."""
        if (
            owner.purpose != LLMCatalogPurpose.IMAGE_GENERATION
            or owner.provider_integration_id is None
        ):
            raise ValueError("Image publication requires an integration image owner.")
        self._validate_entry_scope(owner, entries)
        identifiers = {entry.provider_model_identifier for entry in entries}
        existing_result = await session.execute(
            sa.select(RDBImageGenerationCatalogEntry.provider_model_identifier)
            .where(RDBImageGenerationCatalogEntry.catalog_id == owner.id)
            .with_for_update()
        )
        obsolete = sorted(set(existing_result.scalars()) - identifiers)
        for start in range(0, len(entries), _ROW_BATCH_SIZE):
            values = [
                {
                    "id": uuid7().hex,
                    "catalog_id": owner.id,
                    "updated_at": finished_at,
                    **dataclasses.asdict(entry),
                }
                for entry in entries[start : start + _ROW_BATCH_SIZE]
            ]
            statement = insert(RDBImageGenerationCatalogEntry).values(values)
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=["catalog_id", "provider_model_identifier"],
                    set_={
                        column.name: statement.excluded[column.name]
                        for column in RDBImageGenerationCatalogEntry.__table__.columns
                        if column.name
                        not in {
                            "id",
                            "catalog_id",
                            "provider_model_identifier",
                            "created_at",
                        }
                    },
                )
            )
        for start in range(0, len(obsolete), _ROW_BATCH_SIZE):
            await session.execute(
                sa.delete(RDBImageGenerationCatalogEntry).where(
                    RDBImageGenerationCatalogEntry.catalog_id == owner.id,
                    RDBImageGenerationCatalogEntry.provider_model_identifier.in_(
                        obsolete[start : start + _ROW_BATCH_SIZE]
                    ),
                )
            )
        self._record_success(
            owner, entries=entries, diagnostics=diagnostics, finished_at=finished_at
        )
        owner.image_usable = True
        await session.flush()

    async def get_selectable_entries_for_identities(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        identities: Sequence[ConfiguredModelIdentity],
    ) -> dict[ConfiguredModelIdentity, CatalogEntryWithCatalog]:
        """Read exact choices in bulk, locking current owners in stable ID order."""
        integrations = {}
        for integration_id in sorted(
            {identity.integration_id for identity in identities}
        ):
            integration = await self.lock_integration(
                session,
                integration_id=integration_id,
                workspace_id=workspace_id,
                shared=True,
            )
            if integration is not None:
                integrations[integration_id] = integration
        authorized = tuple(
            identity
            for identity in identities
            if identity.integration_id in integrations
            and integrations[identity.integration_id].provider == identity.provider
        )
        if not authorized:
            return {}
        system_providers = {
            identity.provider
            for identity in authorized
            if identity.provider not in INTEGRATION_SCOPED_CATALOG_PROVIDERS
        }
        owners_result = await session.execute(
            sa.select(RDBLLMCatalog)
            .where(
                RDBLLMCatalog.purpose == LLMCatalogPurpose.CONVERSATION,
                sa.or_(
                    RDBLLMCatalog.provider_integration_id.in_(integrations),
                    sa.and_(
                        RDBLLMCatalog.scope == LLMCatalogScope.SYSTEM,
                        RDBLLMCatalog.provider.in_(system_providers),
                    ),
                ),
            )
            .order_by(RDBLLMCatalog.id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        owners = list(owners_result.scalars())
        exact_owners = {}
        for identity in authorized:
            owner = next(
                (
                    item
                    for item in owners
                    if item.provider == identity.provider
                    and item.provider_integration_id == identity.integration_id
                ),
                None,
            )
            if owner is None and identity.provider in system_providers:
                owner = next(
                    (
                        item
                        for item in owners
                        if item.provider == identity.provider
                        and item.scope == LLMCatalogScope.SYSTEM
                    ),
                    None,
                )
            if owner is not None:
                exact_owners[identity] = owner
        if not exact_owners:
            return {}
        rows_result = await session.execute(
            sa.select(RDBLLMCatalogEntry)
            .where(
                sa.tuple_(
                    RDBLLMCatalogEntry.catalog_id,
                    RDBLLMCatalogEntry.provider_model_identifier,
                ).in_(
                    {
                        (owner.id, identity.model_identifier)
                        for identity, owner in exact_owners.items()
                    }
                ),
                RDBLLMCatalogEntry.visibility_status
                == LLMCatalogEntryVisibility.SELECTABLE,
            )
            .execution_options(populate_existing=True)
        )
        rows = {
            (row.catalog_id, row.provider_model_identifier): row
            for row in rows_result.scalars()
        }
        return {
            identity: CatalogEntryWithCatalog(
                catalog=self.build_catalog(owner), entry=self._build_entry(row)
            )
            for identity, owner in exact_owners.items()
            if (row := rows.get((owner.id, identity.model_identifier))) is not None
        }

    async def _read_owner_for_integration(
        self,
        session: AsyncSession,
        *,
        integration_id: str,
        workspace_id: str,
        purpose: LLMCatalogPurpose,
        require_enabled: bool,
    ) -> RDBLLMCatalog | None:
        integration = await self.lock_integration(
            session,
            integration_id=integration_id,
            workspace_id=workspace_id,
            shared=True,
        )
        if integration is None or (require_enabled and not integration.enabled):
            return None
        result = await session.execute(
            sa.select(RDBLLMCatalog.id).where(
                RDBLLMCatalog.provider_integration_id == integration_id,
                RDBLLMCatalog.purpose == purpose,
            )
        )
        catalog_id = result.scalar_one_or_none()
        if (
            catalog_id is None
            and purpose == LLMCatalogPurpose.CONVERSATION
            and integration.provider not in INTEGRATION_SCOPED_CATALOG_PROVIDERS
        ):
            result = await session.execute(
                sa.select(RDBLLMCatalog.id).where(
                    RDBLLMCatalog.scope == LLMCatalogScope.SYSTEM,
                    RDBLLMCatalog.provider == integration.provider,
                    RDBLLMCatalog.purpose == purpose,
                )
            )
            catalog_id = result.scalar_one_or_none()
        return (
            None
            if catalog_id is None
            else await self.lock_catalog(session, catalog_id=catalog_id, shared=True)
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
        owner = await self._read_owner_for_integration(
            session,
            integration_id=integration_id,
            workspace_id=workspace_id,
            purpose=purpose,
            require_enabled=False,
        )
        if owner is None:
            return None
        filters = [
            RDBLLMCatalogEntry.catalog_id == owner.id,
            RDBLLMCatalogEntry.visibility_status
            == LLMCatalogEntryVisibility.SELECTABLE,
        ]
        if search is not None:
            filters.append(
                sa.or_(
                    RDBLLMCatalogEntry.display_name.ilike(f"%{search}%"),
                    RDBLLMCatalogEntry.provider_model_identifier.ilike(f"%{search}%"),
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
                RDBLLMCatalogEntry.display_name,
                RDBLLMCatalogEntry.provider_model_identifier,
            )
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        return LLMCatalogEntryList(
            catalog=self.build_catalog(owner),
            entries=[self._build_entry(row) for row in result.scalars()],
            total=total_result.scalar_one(),
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
        """Copy current exact data/price with existing conversation predicates."""
        owner = await self._read_owner_for_integration(
            session,
            integration_id=integration_id,
            workspace_id=workspace_id,
            purpose=purpose,
            require_enabled=False,
        )
        if owner is None:
            return None
        result = await session.execute(
            sa.select(RDBLLMCatalogEntry)
            .where(
                RDBLLMCatalogEntry.catalog_id == owner.id,
                RDBLLMCatalogEntry.provider_model_identifier == model_identifier,
                RDBLLMCatalogEntry.visibility_status
                == LLMCatalogEntryVisibility.SELECTABLE,
            )
            .execution_options(populate_existing=True)
        )
        row = result.scalar_one_or_none()
        return (
            None
            if row is None
            else CatalogEntryWithCatalog(
                catalog=self.build_catalog(owner), entry=self._build_entry(row)
            )
        )

    async def list_image_generation_entries_by_integration(
        self, session: AsyncSession, *, integration_id: str, workspace_id: str
    ) -> ImageGenerationCatalogEntryList | None:
        owner = await self._read_owner_for_integration(
            session,
            integration_id=integration_id,
            workspace_id=workspace_id,
            purpose=LLMCatalogPurpose.IMAGE_GENERATION,
            require_enabled=False,
        )
        if owner is None:
            return None
        result = await session.execute(
            sa.select(RDBImageGenerationCatalogEntry)
            .where(
                RDBImageGenerationCatalogEntry.catalog_id == owner.id,
                RDBImageGenerationCatalogEntry.visibility_status
                == LLMCatalogEntryVisibility.SELECTABLE,
            )
            .order_by(
                RDBImageGenerationCatalogEntry.recommendation_rank.asc().nullslast(),
                RDBImageGenerationCatalogEntry.display_name,
                RDBImageGenerationCatalogEntry.provider_model_identifier,
            )
            .execution_options(populate_existing=True)
        )
        entries = [self._build_image_entry(row) for row in result.scalars()]
        return ImageGenerationCatalogEntryList(
            catalog=self.build_catalog(owner), entries=entries, total=len(entries)
        )

    async def get_selectable_image_generation_entry(
        self,
        session: AsyncSession,
        *,
        integration_id: str,
        workspace_id: str,
        model_identifier: str,
    ) -> ImageGenerationCatalogEntryWithCatalog | None:
        owner = await self._read_owner_for_integration(
            session,
            integration_id=integration_id,
            workspace_id=workspace_id,
            purpose=LLMCatalogPurpose.IMAGE_GENERATION,
            require_enabled=True,
        )
        if (
            owner is None
            or owner.image_usable is not True
            or owner.last_success_at is None
        ):
            return None
        result = await session.execute(
            sa.select(RDBImageGenerationCatalogEntry)
            .where(
                RDBImageGenerationCatalogEntry.catalog_id == owner.id,
                RDBImageGenerationCatalogEntry.provider_model_identifier
                == model_identifier,
                RDBImageGenerationCatalogEntry.visibility_status
                == LLMCatalogEntryVisibility.SELECTABLE,
            )
            .execution_options(populate_existing=True)
        )
        row = result.scalar_one_or_none()
        return (
            None
            if row is None
            else ImageGenerationCatalogEntryWithCatalog(
                catalog=self.build_catalog(owner), entry=self._build_image_entry(row)
            )
        )

    async def get_system_catalog(
        self,
        session: AsyncSession,
        *,
        provider: LLMProvider,
        purpose: LLMCatalogPurpose,
    ) -> LLMCatalog | None:
        result = await session.execute(
            sa.select(RDBLLMCatalog)
            .where(
                RDBLLMCatalog.scope == LLMCatalogScope.SYSTEM,
                RDBLLMCatalog.provider == provider,
                RDBLLMCatalog.purpose == purpose,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        owner = result.scalar_one_or_none()
        return None if owner is None else self.build_catalog(owner)

    async def get_by_integration(
        self,
        session: AsyncSession,
        *,
        integration_id: str,
        workspace_id: str,
        purpose: LLMCatalogPurpose,
    ) -> LLMCatalog | None:
        integration = await self.lock_integration(
            session,
            integration_id=integration_id,
            workspace_id=workspace_id,
            shared=True,
        )
        if integration is None:
            return None
        result = await session.execute(
            sa.select(RDBLLMCatalog)
            .where(
                RDBLLMCatalog.provider_integration_id == integration_id,
                RDBLLMCatalog.purpose == purpose,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        owner = result.scalar_one_or_none()
        return None if owner is None else self.build_catalog(owner)

    async def get_sync_status(
        self, session: AsyncSession, *, catalog: LLMCatalog
    ) -> LLMCatalogSyncStatus | None:
        owner = await self.lock_catalog(session, catalog_id=catalog.id, shared=True)
        return current_sync_status(owner)

    async def get_latest_integration_sync_for_workspace(
        self, session: AsyncSession, *, workspace_id: str
    ) -> LLMCatalogSyncStatus | None:
        result = await session.execute(
            sa.select(RDBLLMCatalog)
            .join(
                RDBLLMProviderIntegration,
                RDBLLMProviderIntegration.id == RDBLLMCatalog.provider_integration_id,
            )
            .where(
                RDBLLMProviderIntegration.workspace_id == workspace_id,
                RDBLLMCatalog.sync_started_at.is_not(None),
            )
            .order_by(RDBLLMCatalog.sync_started_at.desc(), RDBLLMCatalog.id)
            .limit(1)
            .execution_options(populate_existing=True)
        )
        owner = result.scalar_one_or_none()
        return None if owner is None else current_sync_status(owner)

    async def get_current_counts(
        self, session: AsyncSession, *, catalog: LLMCatalog
    ) -> LLMCatalogCounts | None:
        owner = await self.lock_catalog(session, catalog_id=catalog.id, shared=True)
        return (
            None
            if owner.last_success_at is None
            else LLMCatalogCounts(
                visible_count=owner.visible_count, hidden_count=owner.hidden_count
            )
        )

    @staticmethod
    def policy_sync(status: LLMCatalogSyncStatus | None) -> CatalogSyncState | None:
        if status is None:
            return None
        return CatalogSyncState(
            owner_id=status.owner_id,
            work_token=status.work_token,
            status=status.status,
            started_at=status.started_at,
            finished_at=status.finished_at,
            automatic_retry_blocked=CatalogRetryPolicy.from_diagnostics(
                status.diagnostics
            ).automatic_retry_blocked,
        )

    @staticmethod
    def build_catalog(owner: RDBLLMCatalog) -> LLMCatalog:
        return LLMCatalog(
            id=owner.id,
            scope=owner.scope,
            provider=owner.provider,
            purpose=owner.purpose,
            provider_integration_id=owner.provider_integration_id,
            entry_count=owner.entry_count,
            visible_count=owner.visible_count,
            hidden_count=owner.hidden_count,
            last_success_at=owner.last_success_at,
            image_usable=owner.image_usable,
            diagnostics=owner.diagnostics,
            sync_status=current_sync_status(owner),
        )

    @staticmethod
    def _validate_conversation_capabilities(
        entries: list[LLMCatalogEntryCreate],
    ) -> None:
        """Require current raw compiler output at the new publication boundary."""
        for entry in entries:
            if entry.normalized_capabilities.get("capability_schema_version") != 3:
                raise ValueError(
                    "Conversation publication requires final v3 capabilities."
                )
            if (
                entry.projection_metadata is None
                or entry.projection_metadata.get("capability_compiler_revision")
                != CAPABILITY_PROJECTION_REVISION
            ):
                raise ValueError(
                    "Conversation publication requires the current capability compiler."
                )
            ModelCapabilities.model_validate(entry.normalized_capabilities)

    @staticmethod
    def _validate_entry_scope(
        owner: RDBLLMCatalog,
        entries: list[LLMCatalogEntryCreate] | list[ImageGenerationCatalogEntryCreate],
    ) -> None:
        identifiers: set[str] = set()
        for entry in entries:
            if (
                entry.provider != owner.provider
                or entry.provider_integration_id != owner.provider_integration_id
                or not entry.provider_model_identifier
                or entry.provider_model_identifier in identifiers
            ):
                raise ValueError(
                    "Prepared entries do not belong to one exact catalog scope."
                )
            identifiers.add(entry.provider_model_identifier)

    @staticmethod
    def _record_success(
        owner: RDBLLMCatalog,
        *,
        entries: list[LLMCatalogEntryCreate] | list[ImageGenerationCatalogEntryCreate],
        diagnostics: dict[str, Any] | None,
        finished_at: datetime.datetime,
    ) -> None:
        owner.entry_count = len(entries)
        owner.visible_count = sum(
            entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
            for entry in entries
        )
        owner.hidden_count = owner.entry_count - owner.visible_count
        owner.last_success_at = finished_at
        owner.diagnostics = diagnostics

    @staticmethod
    def _build_entry(row: RDBLLMCatalogEntry) -> LLMCatalogEntry:
        return LLMCatalogEntry(
            id=row.id,
            catalog_id=row.catalog_id,
            provider=row.provider,
            provider_model_identifier=row.provider_model_identifier,
            display_name=row.display_name,
            normalized_capabilities=row.normalized_capabilities,
            supported_execution_options=row.supported_execution_options,
            lifecycle_status=row.lifecycle_status,
            visibility_status=row.visibility_status,
            provider_integration_id=row.provider_integration_id,
            publisher=row.publisher,
            family=row.family,
            source_metadata=row.source_metadata,
            projection_metadata=row.projection_metadata,
            hidden_reason=row.hidden_reason,
            pricing=ModelPricingDefinition.model_validate(row.pricing),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _build_image_entry(
        row: RDBImageGenerationCatalogEntry,
    ) -> ImageGenerationCatalogEntry:
        return ImageGenerationCatalogEntry(
            id=row.id,
            catalog_id=row.catalog_id,
            provider=row.provider,
            provider_model_identifier=row.provider_model_identifier,
            display_name=row.display_name,
            description=row.description,
            recommendation_rank=row.recommendation_rank,
            lifecycle_status=row.lifecycle_status,
            visibility_status=row.visibility_status,
            provider_integration_id=row.provider_integration_id,
            source_metadata=row.source_metadata,
            projection_metadata=row.projection_metadata,
            hidden_reason=row.hidden_reason,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
