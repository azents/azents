"""Completed current maintenance and exact optional-context source reads."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.model_catalog_source import CATALOG_SOURCE_KEY
from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import (
    CapturedContextSource,
    ContextModelRequest,
    ModelMetadataSource,
)


@dataclass(frozen=True)
class ModelMetadataReadRepository:
    """Own finished reads, with whole-current views reserved for maintenance."""

    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    source_repository: Annotated[
        ModelMetadataSourceRepository, Depends(ModelMetadataSourceRepository)
    ]

    async def capture_current(self) -> ModelMetadataSource | None:
        """Assemble a detached complete current source for maintenance only."""
        async with self.session_manager() as session:
            return await self.source_repository.get_current(
                session, source_key=CATALOG_SOURCE_KEY
            )

    async def capture_for_context(
        self, *, requests: Sequence[ContextModelRequest]
    ) -> CapturedContextSource:
        """Return only requested exact maxima; no whole-source restoration."""
        if not requests:
            return CapturedContextSource(models=())
        async with self.session_manager() as session:
            return await self.source_repository.capture_for_context(
                session, requests=requests
            )
