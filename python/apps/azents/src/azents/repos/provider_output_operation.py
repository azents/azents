"""Completed database operations for generated provider output metadata."""

import dataclasses
import datetime
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.exchange_file.data import ExchangeFile, ExchangeFileCreate
from azents.repos.file_metadata_authority import (
    FileMetadataAuthorityRepository,
    FileResourceAuthority,
)
from azents.repos.model_file import ModelFileRepository
from azents.repos.model_file.data import ModelFile, ModelFileCreate


class ProviderOutputOperationError(ValueError):
    """Provider-output metadata failed a stable operation precondition."""


@dataclasses.dataclass(frozen=True)
class ProviderOutputFileMetadata:
    """Database metadata for one deterministic generated image."""

    exchange_source: ExchangeFileCreate
    exchange_preview: ExchangeFileCreate | None
    preview_width: int | None
    preview_height: int | None
    preview_generated_at: datetime.datetime | None
    model_file: ModelFileCreate


@dataclasses.dataclass
class ProviderOutputOperationRepository:
    """Own provider-output authority, retry, and cleanup transactions."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    exchange_file_repository: Annotated[
        ExchangeFileRepository,
        Depends(ExchangeFileRepository),
    ]
    model_file_repository: Annotated[
        ModelFileRepository,
        Depends(ModelFileRepository),
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ]
    agent_run_repository: Annotated[
        AgentRunRepository,
        Depends(AgentRunRepository),
    ]

    @property
    def authority_repository(self) -> FileMetadataAuthorityRepository:
        """Return the shared database-only authority validator."""
        return FileMetadataAuthorityRepository(
            agent_session_repository=self.agent_session_repository,
            agent_run_repository=self.agent_run_repository,
        )

    async def validate_scope(self, authority: FileResourceAuthority) -> str:
        """Validate scope in one completed operation and return its root."""
        async with self.session_manager() as session:
            if not await self.authority_repository.validate(
                session,
                authority,
                lock=False,
            ):
                raise ProviderOutputOperationError(
                    "Generated image output scope is unavailable."
                )
            return authority.root_session_id

    async def load_existing_object_keys(
        self,
        *,
        authority: FileResourceAuthority,
        generated_images: Sequence[ProviderOutputFileMetadata],
    ) -> set[str]:
        """Validate retry metadata and return already persisted object keys."""
        async with self.session_manager() as session:
            if not await self.authority_repository.validate(
                session,
                authority,
                lock=False,
            ):
                raise ProviderOutputOperationError(
                    "Generated image output scope is unavailable."
                )
            return await self._validated_persisted_object_keys(
                session,
                generated_images,
            )

    async def load_cleanup_protected_keys(
        self,
        *,
        authority: FileResourceAuthority,
        generated_images: Sequence[ProviderOutputFileMetadata],
    ) -> set[str]:
        """Return admitted retry keys protected from compensation deletion."""
        async with self.session_manager() as session:
            run = await self.agent_run_repository.get_by_id(
                session,
                authority.run_id,
            )
            if run is None or run.session_id != authority.session_id:
                return set()
            return await self._validated_persisted_object_keys(
                session,
                generated_images,
            )

    async def persist_in_session(
        self,
        session: AsyncSession,
        *,
        authority: FileResourceAuthority,
        generated_images: Sequence[ProviderOutputFileMetadata],
    ) -> None:
        """Revalidate locked authority and admit metadata in caller transaction."""
        if not generated_images:
            return
        if not await self.authority_repository.validate(
            session,
            authority,
            lock=True,
        ):
            raise ProviderOutputOperationError(
                "Generated image output scope is unavailable."
            )
        if any(
            image.exchange_source.retention_root_session_id != authority.root_session_id
            for image in generated_images
        ):
            raise ProviderOutputOperationError("Generated image output scope changed.")
        await self._validated_persisted_object_keys(session, generated_images)
        for image in generated_images:
            source = await self.exchange_file_repository.get_by_id(
                session,
                image.exchange_source.id,
            )
            if source is None:
                source = await self.exchange_file_repository.create(
                    session,
                    image.exchange_source,
                )
            _validate_existing_exchange_file(source, image.exchange_source)

            preview = image.exchange_preview
            if preview is not None:
                existing_preview = await self.exchange_file_repository.get_by_id(
                    session,
                    preview.id,
                )
                if existing_preview is None:
                    existing_preview = await self.exchange_file_repository.create(
                        session,
                        preview,
                    )
                _validate_existing_exchange_file(existing_preview, preview)
                if (
                    image.preview_width is None
                    or image.preview_height is None
                    or image.preview_generated_at is None
                ):
                    raise ProviderOutputOperationError(
                        "Generated image preview metadata is incomplete."
                    )
                if source.preview_thumbnail_file_id not in {None, preview.id}:
                    raise ProviderOutputOperationError(
                        "Generated image output identity collided."
                    )
                if source.preview_thumbnail_file_id is None:
                    await (self.exchange_file_repository.set_preview_thumbnail_file_id)(
                        session,
                        file_id=image.exchange_source.id,
                        preview_thumbnail_file_id=preview.id,
                        preview_thumbnail_media_type=preview.media_type,
                        preview_thumbnail_width=image.preview_width,
                        preview_thumbnail_height=image.preview_height,
                        preview_generated_at=image.preview_generated_at,
                    )

            model_file = await self.model_file_repository.get_by_id(
                session,
                image.model_file.id,
            )
            if model_file is None:
                model_file = await self.model_file_repository.create(
                    session,
                    image.model_file,
                )
            _validate_existing_model_file(model_file, image.model_file)

    async def _validated_persisted_object_keys(
        self,
        session: AsyncSession,
        generated_images: Sequence[ProviderOutputFileMetadata],
    ) -> set[str]:
        """Validate deterministic identities and return persisted object keys."""
        protected: set[str] = set()
        for image in generated_images:
            source = await self.exchange_file_repository.get_by_id(
                session,
                image.exchange_source.id,
            )
            if source is not None:
                _validate_existing_exchange_file(source, image.exchange_source)
                protected.add(source.object_key)
            preview = image.exchange_preview
            if preview is not None:
                if source is not None and source.preview_thumbnail_file_id not in {
                    None,
                    preview.id,
                }:
                    raise ProviderOutputOperationError(
                        "Generated image output identity collided."
                    )
                existing_preview = await self.exchange_file_repository.get_by_id(
                    session,
                    preview.id,
                )
                if existing_preview is not None:
                    _validate_existing_exchange_file(existing_preview, preview)
                    protected.add(existing_preview.object_key)
            model_file = await self.model_file_repository.get_by_id(
                session,
                image.model_file.id,
            )
            if model_file is not None:
                _validate_existing_model_file(model_file, image.model_file)
                protected.add(model_file.storage_key)
        return protected


def _validate_existing_exchange_file(
    existing: ExchangeFile,
    expected: ExchangeFileCreate,
) -> None:
    """Reject deterministic Exchange identities bound to different bytes."""
    if (
        existing.id != expected.id
        or existing.workspace_id != expected.workspace_id
        or existing.agent_id != expected.agent_id
        or existing.filename != expected.filename
        or existing.media_type != expected.media_type
        or existing.size_bytes != expected.size_bytes
        or existing.sha256 != expected.sha256
        or existing.provenance_kind != expected.provenance_kind
        or existing.source_user_id != expected.source_user_id
        or existing.source_agent_id != expected.source_agent_id
        or existing.source_run_id != expected.source_run_id
        or existing.source_tool_name != expected.source_tool_name
        or existing.source_provider != expected.source_provider
        or existing.source_exchange_file_id != expected.source_exchange_file_id
        or existing.retention_root_session_id != expected.retention_root_session_id
    ):
        raise ProviderOutputOperationError("Generated image output identity collided.")


def _validate_existing_model_file(
    existing: ModelFile,
    expected: ModelFileCreate,
) -> None:
    """Reject deterministic ModelFile identities bound to different bytes."""
    if (
        existing.id != expected.id
        or existing.workspace_id != expected.workspace_id
        or existing.session_id != expected.session_id
        or existing.agent_id != expected.agent_id
        or existing.name != expected.name
        or existing.media_type != expected.media_type
        or existing.kind != expected.kind
        or existing.size_bytes != expected.size_bytes
        or existing.sha256 != expected.sha256
        or existing.created_run_id != expected.created_run_id
        or existing.created_run_index != expected.created_run_index
        or existing.normalized_format != expected.normalized_format
    ):
        raise ProviderOutputOperationError("Generated image output identity collided.")
