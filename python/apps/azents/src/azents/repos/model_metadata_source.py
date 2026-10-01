"""Persistence for durable model metadata source authority."""

import datetime
from typing import Any

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMCatalogAttemptStatus
from azents.core.model_metadata_source import ModelMetadataSourcePayload
from azents.rdb.models.llm_catalog import RDBLLMCatalogSyncAttempt
from azents.rdb.models.model_metadata_source import (
    RDBModelMetadataSource,
    RDBModelMetadataSourceSnapshot,
)
from azents.repos.model_metadata_source_data import (
    ModelMetadataSourceAttempt,
    ModelMetadataSourceSnapshot,
)


class ModelMetadataSourceRepository:
    """Repository for model metadata source authority and snapshots."""

    async def ensure_authority(
        self,
        session: AsyncSession,
        *,
        source_key: str,
    ) -> RDBModelMetadataSource:
        """Create or load the logical source authority row."""
        result = await session.execute(
            insert(RDBModelMetadataSource)
            .values(
                source_key=source_key,
                current_snapshot_id=None,
                latest_attempt_id=None,
            )
            .on_conflict_do_nothing(index_elements=["source_key"])
            .returning(RDBModelMetadataSource)
        )
        authority = result.scalar_one_or_none()
        if authority is None:
            authority = await session.get(RDBModelMetadataSource, source_key)
        if authority is None:
            raise RuntimeError("Model metadata source authority upsert failed.")
        await session.flush()
        return authority

    async def begin_attempt(
        self,
        session: AsyncSession,
        *,
        source_key: str,
        started_at: datetime.datetime,
    ) -> str:
        """Create the latest source attempt and retire abandoned work."""
        authority = await self.ensure_authority(session, source_key=source_key)
        await session.execute(
            sa.update(RDBLLMCatalogSyncAttempt)
            .where(
                RDBLLMCatalogSyncAttempt.catalog_id.is_(None),
                RDBLLMCatalogSyncAttempt.source_key == source_key,
                RDBLLMCatalogSyncAttempt.status == LLMCatalogAttemptStatus.RUNNING,
            )
            .values(
                status=LLMCatalogAttemptStatus.FAILED,
                finished_at=started_at,
                failure_code="ModelMetadataSourceSyncInterrupted",
                failure_message=(
                    "A newer model metadata source synchronization replaced an "
                    "unfinished attempt."
                ),
                action_hint="Use the newer source synchronization result.",
                diagnostics={"failure_category": "source_sync_interrupted"},
            )
        )
        attempt_id = uuid7().hex
        session.add(
            RDBLLMCatalogSyncAttempt(
                id=attempt_id,
                catalog_id=None,
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
        authority.latest_attempt_id = attempt_id
        await session.flush()
        return attempt_id

    async def lock_authority(
        self,
        session: AsyncSession,
        *,
        source_key: str,
    ) -> RDBModelMetadataSource:
        """Lock the source authority for validation and publication."""
        result = await session.execute(
            sa.select(RDBModelMetadataSource)
            .where(RDBModelMetadataSource.source_key == source_key)
            .with_for_update()
        )
        authority = result.scalar_one_or_none()
        if authority is None:
            raise RuntimeError("Model metadata source authority does not exist.")
        return authority

    async def publish_snapshot(
        self,
        session: AsyncSession,
        *,
        authority: RDBModelMetadataSource,
        attempt_id: str,
        source_kind: str,
        source_schema_version: str,
        source_url: str,
        source_hash: str,
        producer_name: str,
        producer_version: str,
        provider_count: int,
        model_count: int,
        payload: ModelMetadataSourcePayload,
        finished_at: datetime.datetime,
        diagnostics: dict[str, Any],
    ) -> ModelMetadataSourceSnapshot | None:
        """Publish a snapshot only while the attempt remains current."""
        if authority.latest_attempt_id != attempt_id:
            return None
        result = await session.execute(
            insert(RDBModelMetadataSourceSnapshot)
            .values(
                id=uuid7().hex,
                source_key=authority.source_key,
                source_kind=source_kind,
                source_schema_version=source_schema_version,
                source_url=source_url,
                source_hash=source_hash,
                producer_name=producer_name,
                producer_version=producer_version,
                provider_count=provider_count,
                model_count=model_count,
                payload=payload.model_dump(mode="json"),
            )
            .on_conflict_do_nothing(
                index_elements=[
                    "source_key",
                    "source_schema_version",
                    "source_hash",
                ]
            )
            .returning(RDBModelMetadataSourceSnapshot)
        )
        snapshot = result.scalar_one_or_none()
        if snapshot is None:
            snapshot_result = await session.execute(
                sa.select(RDBModelMetadataSourceSnapshot).where(
                    RDBModelMetadataSourceSnapshot.source_key == authority.source_key,
                    RDBModelMetadataSourceSnapshot.source_schema_version
                    == source_schema_version,
                    RDBModelMetadataSourceSnapshot.source_hash == source_hash,
                )
            )
            snapshot = snapshot_result.scalar_one()
        authority.current_snapshot_id = snapshot.id
        await session.execute(
            sa.update(RDBLLMCatalogSyncAttempt)
            .where(RDBLLMCatalogSyncAttempt.id == attempt_id)
            .values(
                status=LLMCatalogAttemptStatus.SUCCEEDED,
                finished_at=finished_at,
                produced_snapshot_id=snapshot.id,
                fetched_count=model_count,
                matched_count=model_count,
                skipped_count=0,
                hidden_count=0,
                diagnostics=diagnostics,
            )
        )
        await session.flush()
        return self._build_snapshot(snapshot)

    async def fail_attempt(
        self,
        session: AsyncSession,
        *,
        attempt_id: str,
        finished_at: datetime.datetime,
        failure_code: str,
        failure_message: str,
        action_hint: str,
        fetched_count: int,
        diagnostics: dict[str, Any],
    ) -> None:
        """Record one source synchronization failure."""
        await session.execute(
            sa.update(RDBLLMCatalogSyncAttempt)
            .where(RDBLLMCatalogSyncAttempt.id == attempt_id)
            .values(
                status=LLMCatalogAttemptStatus.FAILED,
                finished_at=finished_at,
                failure_code=failure_code,
                failure_message=failure_message,
                action_hint=action_hint,
                fetched_count=fetched_count,
                matched_count=0,
                skipped_count=fetched_count,
                hidden_count=0,
                diagnostics=diagnostics,
            )
        )
        await session.flush()

    async def get_current(
        self,
        session: AsyncSession,
        *,
        source_key: str,
    ) -> ModelMetadataSourceSnapshot | None:
        """Return the explicitly selected current source snapshot."""
        result = await session.execute(
            sa.select(RDBModelMetadataSourceSnapshot)
            .join(
                RDBModelMetadataSource,
                RDBModelMetadataSource.current_snapshot_id
                == RDBModelMetadataSourceSnapshot.id,
            )
            .where(RDBModelMetadataSource.source_key == source_key)
        )
        snapshot = result.scalar_one_or_none()
        return self._build_snapshot(snapshot) if snapshot is not None else None

    async def get_latest_attempt(
        self,
        session: AsyncSession,
        *,
        source_key: str,
    ) -> ModelMetadataSourceAttempt | None:
        """Return the attempt selected by the source authority."""
        result = await session.execute(
            sa.select(RDBLLMCatalogSyncAttempt)
            .join(
                RDBModelMetadataSource,
                RDBModelMetadataSource.latest_attempt_id == RDBLLMCatalogSyncAttempt.id,
            )
            .where(RDBModelMetadataSource.source_key == source_key)
        )
        attempt = result.scalar_one_or_none()
        return self._build_attempt(attempt) if attempt is not None else None

    @staticmethod
    def _build_snapshot(
        snapshot: RDBModelMetadataSourceSnapshot,
    ) -> ModelMetadataSourceSnapshot:
        return ModelMetadataSourceSnapshot(
            id=snapshot.id,
            source_key=snapshot.source_key,
            source_kind=snapshot.source_kind,
            source_schema_version=snapshot.source_schema_version,
            source_url=snapshot.source_url,
            source_hash=snapshot.source_hash,
            producer_name=snapshot.producer_name,
            producer_version=snapshot.producer_version,
            provider_count=snapshot.provider_count,
            model_count=snapshot.model_count,
            payload=ModelMetadataSourcePayload.model_validate(snapshot.payload),
            created_at=snapshot.created_at,
        )

    @staticmethod
    def _build_attempt(
        attempt: RDBLLMCatalogSyncAttempt,
    ) -> ModelMetadataSourceAttempt:
        return ModelMetadataSourceAttempt(
            id=attempt.id,
            source_key=attempt.source_key,
            status=attempt.status,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
            produced_snapshot_id=attempt.produced_snapshot_id,
            failure_code=attempt.failure_code,
            failure_message=attempt.failure_message,
            action_hint=attempt.action_hint,
            fetched_count=attempt.fetched_count,
            diagnostics=attempt.diagnostics,
        )
