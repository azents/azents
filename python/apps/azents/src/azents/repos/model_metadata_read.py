"""Completed capture of the selected local validated metadata source."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.model_catalog_source import CATALOG_SOURCE_KEY
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot


@dataclass(frozen=True)
class ModelMetadataReadRepository:
    """Capture local authority without source/provider fetching."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    source_snapshot_repository: Annotated[
        ModelMetadataSourceRepository, Depends(ModelMetadataSourceRepository)
    ]

    async def capture(self) -> ModelMetadataSourceSnapshot | None:
        """Finish the selected source read before returning its detached snapshot."""
        async with self.session_manager() as session:
            result = await self.source_snapshot_repository.get_current(
                session,
                source_key=CATALOG_SOURCE_KEY,
            )
        return result
