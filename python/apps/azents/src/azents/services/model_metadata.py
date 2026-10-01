"""Operation-local reads of the validated generic model metadata authority."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider
from azents.core.model_metadata_source import SourceModelMatch, lookup_source_model
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot
from azents.services.model_metadata_source import GENAI_PRICES_SOURCE_KEY


@dataclasses.dataclass(frozen=True)
class CapturedContextSource:
    """One captured context authority, including an explicitly absent source."""

    snapshot: ModelMetadataSourceSnapshot | None


@dataclasses.dataclass(frozen=True)
class ModelMetadataService:
    """Capture local validated metadata without source or provider fetches."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    source_snapshot_repository: Annotated[
        ModelMetadataSourceRepository, Depends(ModelMetadataSourceRepository)
    ]

    async def capture(self) -> ModelMetadataSourceSnapshot | None:
        """Capture the explicitly selected generic source snapshot."""
        async with self.session_manager() as session:
            return await self.source_snapshot_repository.get_current(
                session,
                source_key=GENAI_PRICES_SOURCE_KEY,
            )

    async def capture_for_context(
        self, *, capability_maximums: Sequence[int | None]
    ) -> ModelMetadataSourceSnapshot | None:
        """Read fallback metadata only when a saved maximum needs supplementation."""
        if all(maximum is not None for maximum in capability_maximums):
            return None
        return await self.capture()

    @staticmethod
    def lookup(
        snapshot: ModelMetadataSourceSnapshot | None,
        *,
        provider: LLMProvider,
        model_identifier: str,
    ) -> SourceModelMatch | None:
        """Resolve one semantic model from a captured generic source snapshot."""
        if snapshot is None:
            return None
        return lookup_source_model(
            snapshot.payload,
            provider=provider,
            model_identifier=model_identifier,
        )

    @staticmethod
    def maximum_input_tokens(
        snapshot: ModelMetadataSourceSnapshot | None,
        *,
        provider: LLMProvider,
        model_identifier: str,
    ) -> int | None:
        """Read one positive source maximum from a captured local snapshot."""
        match = ModelMetadataService.lookup(
            snapshot,
            provider=provider,
            model_identifier=model_identifier,
        )
        return match.model.context_window if match is not None else None
