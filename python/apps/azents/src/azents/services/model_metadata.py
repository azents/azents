"""Exact, operation-local reads for missing saved context maximums."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends

from azents.core.agent import AgentModelSelection
from azents.core.enums import LLMProvider
from azents.repos.model_metadata_read import ModelMetadataReadRepository
from azents.repos.model_metadata_source_data import (
    CapturedContextSource,
    ContextModelRequest,
)


@dataclasses.dataclass(frozen=True)
class ModelMetadataService:
    """Read only exact current maxima without restoring a source dataset."""

    repository: Annotated[
        ModelMetadataReadRepository, Depends(ModelMetadataReadRepository)
    ]

    async def capture_for_context(
        self, *, requests: Sequence[ContextModelRequest]
    ) -> CapturedContextSource:
        """Capture the requested exact models, sharing one completed read."""
        if not requests:
            return CapturedContextSource(models=())
        return await self.repository.capture_for_context(requests=requests)

    @staticmethod
    def context_requests(
        selections: Sequence[AgentModelSelection],
    ) -> tuple[ContextModelRequest, ...]:
        """Request only models whose saved hard maximum is missing."""
        return tuple(
            ContextModelRequest(
                provider=selection.provider,
                model_identifier=selection.model_identifier,
            )
            for selection in selections
            if selection.normalized_capabilities.context_window.max_input_tokens is None
        )

    @staticmethod
    def maximum_input_tokens(
        source: CapturedContextSource | None,
        *,
        provider: LLMProvider,
        model_identifier: str,
    ) -> int | None:
        """Read a requested positive maximum from one narrow immutable capture."""
        if source is None:
            return None
        for model in source.models:
            if (
                model.provider == provider
                and model.model_identifier == model_identifier
            ):
                maximum = model.max_input_tokens
                return maximum if maximum is not None and maximum > 0 else None
        return None
