"""Detached exact inputs for active metadata capture and locked revalidation."""

import dataclasses
from collections.abc import Mapping
from typing import Any

from azents.core.active_model_capabilities import (
    ActiveModelMetadataUnavailable,
    CapturedStoredChoice,
    ConfiguredModelIdentity,
)
from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.repos.model_metadata_source_data import (
    SourceModelExpectation,
    SourceProjectionMetadata,
)


@dataclasses.dataclass(frozen=True)
class CapturedCatalogChoice:
    """Current inputs excluding clocks, sync state and old capability views."""

    identity: ConfiguredModelIdentity
    catalog_id: str | None
    configuration_version: int | None
    source_metadata: Mapping[str, Any] | None
    supported_execution_options: tuple[ModelExecutionOptionId, ...]
    model_developer: LLMModelDeveloper | None
    failure: ActiveModelMetadataUnavailable | None


@dataclasses.dataclass(frozen=True)
class CapturedActiveChoiceInputs:
    workspace_id: str
    choices: tuple[CapturedStoredChoice | ActiveModelMetadataUnavailable, ...]
    catalog_choices: tuple[CapturedCatalogChoice, ...]
    source_metadata: SourceProjectionMetadata | None
    source_expectations: tuple[SourceModelExpectation, ...]


@dataclasses.dataclass(frozen=True)
class CapturedIntegrationScope:
    integration_id: str
    provider: LLMProvider | None
    configuration_version: int | None


@dataclasses.dataclass(frozen=True)
class ActiveReadScope:
    """Descriptive integration/source observation; not final acceptance authority."""

    workspace_id: str
    integrations: tuple[CapturedIntegrationScope, ...]
    source_metadata: SourceProjectionMetadata | None
