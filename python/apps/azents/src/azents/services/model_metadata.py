"""Operation-local reads of the validated retained-source DB authority."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider
from azents.core.model_source_metadata import (
    SourceModelMetadata,
    lookup_model_source_metadata,
    source_max_input_tokens,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import LiteLLMSourceSnapshotRepository
from azents.repos.llm_catalog.data import LiteLLMSourceSnapshot


@dataclasses.dataclass(frozen=True)
class ModelMetadataService:
    """Capture local validated metadata without source or provider fetches."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    source_snapshot_repository: Annotated[
        LiteLLMSourceSnapshotRepository, Depends(LiteLLMSourceSnapshotRepository)
    ]

    async def capture(self) -> LiteLLMSourceSnapshot | None:
        """Capture one validated source snapshot for a read or operation.

        :returns: current validated source including ID/hash/payload, or no source
        """
        async with self.session_manager() as session:
            return await self.source_snapshot_repository.get_latest_authoritative(
                session,
                source_key="litellm_model_cost",
            )

    async def capture_for_context(
        self, *, capability_maximums: Sequence[int | None]
    ) -> LiteLLMSourceSnapshot | None:
        """Read fallback metadata only when a saved maximum needs supplementation.

        :param capability_maximums: maxima for the models sharing one budget/read
        :returns: one validated source snapshot or no fallback is needed/available
        """
        if all(maximum is not None for maximum in capability_maximums):
            return None
        return await self.capture()

    @staticmethod
    def lookup(
        snapshot: LiteLLMSourceSnapshot | None,
        *,
        provider: LLMProvider,
        model_identifier: str,
    ) -> SourceModelMetadata | None:
        """Resolve one semantic model from a previously captured snapshot.

        :param snapshot: operation/read-local validated source snapshot
        :param provider: saved provider identity
        :param model_identifier: exact saved raw provider model ID
        :returns: exact source match or unknown metadata
        """
        if snapshot is None:
            return None
        return lookup_model_source_metadata(
            provider=provider,
            model_identifier=model_identifier,
            payload=snapshot.payload,
        )

    @staticmethod
    def maximum_input_tokens(
        snapshot: LiteLLMSourceSnapshot | None,
        *,
        provider: LLMProvider,
        model_identifier: str,
    ) -> int | None:
        """Read one positive source maximum from a captured local snapshot.

        :param snapshot: operation/read-local validated source snapshot
        :param provider: saved provider identity
        :param model_identifier: exact saved raw provider model ID
        :returns: positive source input maximum or unknown metadata
        """
        return source_max_input_tokens(
            ModelMetadataService.lookup(
                snapshot,
                provider=provider,
                model_identifier=model_identifier,
            )
        )
