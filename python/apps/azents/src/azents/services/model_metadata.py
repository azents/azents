"""Operation-local reads of the selected descriptive model source."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends

from azents.core.enums import LLMProvider
from azents.core.model_catalog_identity import lookup_catalog_model
from azents.core.model_catalog_source import CatalogSourceModel
from azents.repos.model_metadata_read import ModelMetadataReadRepository
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot


@dataclasses.dataclass(frozen=True)
class ModelMetadataService:
    """Read stored new-source evidence, never a remote or retired source."""

    repository: Annotated[
        ModelMetadataReadRepository, Depends(ModelMetadataReadRepository)
    ]

    async def capture(self) -> ModelMetadataSourceSnapshot | None:
        """Capture only the explicitly selected new source family."""
        return await self.repository.capture()

    async def capture_for_context(
        self, *, capability_maximums: Sequence[int | None]
    ) -> ModelMetadataSourceSnapshot | None:
        """Skip optional source work when every saved maximum is already known."""
        if all(maximum is not None for maximum in capability_maximums):
            return None
        return await self.capture()

    @staticmethod
    def lookup(
        snapshot: ModelMetadataSourceSnapshot | None,
        *,
        provider: LLMProvider,
        model_identifier: str,
    ) -> CatalogSourceModel | None:
        """Resolve exact adopted source addressing without provider/name inference."""
        if snapshot is None:
            return None
        return lookup_catalog_model(
            snapshot.payload, provider=provider, model_identifier=model_identifier
        )

    @staticmethod
    def maximum_input_tokens(
        snapshot: ModelMetadataSourceSnapshot | None,
        *,
        provider: LLMProvider,
        model_identifier: str,
    ) -> int | None:
        """Read an explicit positive input maximum from one immutable capture."""
        model = ModelMetadataService.lookup(
            snapshot, provider=provider, model_identifier=model_identifier
        )
        if model is None:
            return None
        maximum = model.facts.max_input_tokens.value
        return maximum if maximum is not None and maximum > 0 else None
