"""Shadow catalog projections from durable Pydantic ecosystem metadata."""

import dataclasses
import hashlib
import importlib.metadata
import json
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMCatalogPurpose,
    LLMModelDeveloper,
    LLMModelLifecycleStatus,
    LLMProvider,
)
from azents.core.model_metadata_source import (
    ModelMetadataSourcePayload,
    SourceModelRecord,
    SourceProviderRecord,
)
from azents.engine.providers.model_profiles import (
    RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
    resolve_runtime_model_profile,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog.data import (
    CatalogProjectionProvenance,
    LLMCatalogEntryCreate,
)
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot
from azents.services.llm_catalog import model_freshness_rank
from azents.services.model_listing.providers import (
    _openai_supported_execution_options,
)
from azents.services.model_metadata_source import ModelMetadataSourceSyncService

MODEL_METADATA_PROJECTION_SCHEMA_VERSION = "1"
MODEL_METADATA_PROJECTION_POLICY_REVISION = "1"
_SYSTEM_SOURCE_PROVIDERS: dict[LLMProvider, str] = {
    LLMProvider.OPENAI: "openai",
    LLMProvider.ANTHROPIC: "anthropic",
    LLMProvider.GOOGLE_GEMINI: "google",
}


@dataclasses.dataclass(frozen=True)
class SystemCatalogShadowSummary:
    """One prepared non-current system projection."""

    provider: LLMProvider
    catalog_id: str
    candidate_snapshot_id: str
    visible_count: int
    hidden_count: int
    projection_fingerprint: str


class ModelMetadataProjectionError(RuntimeError):
    """Replacement metadata cannot produce a complete system projection."""


@dataclasses.dataclass(frozen=True)
class SystemCatalogShadowProjectionService:
    """Prepare replacement system projections without changing current pointers."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    catalog_repository: Annotated[LLMCatalogRepository, Depends(LLMCatalogRepository)]
    source_sync_service: Annotated[
        ModelMetadataSourceSyncService, Depends(ModelMetadataSourceSyncService)
    ]

    async def prepare_candidates(self) -> list[SystemCatalogShadowSummary]:
        """Refresh the replacement source and create non-current candidates."""
        source = await self.source_sync_service.sync_current_source()
        projections = [
            (
                provider,
                project_system_shadow_entries(
                    provider=provider,
                    source=source,
                ),
                projection_fingerprint(
                    provider=provider,
                    source=source,
                ),
            )
            for provider in _SYSTEM_SOURCE_PROVIDERS
        ]
        summaries: list[SystemCatalogShadowSummary] = []
        for provider, entries, fingerprint in projections:
            provenance = CatalogProjectionProvenance(
                metadata_source_snapshot_id=source.id,
                projection_schema_version=MODEL_METADATA_PROJECTION_SCHEMA_VERSION,
                runtime_profile_resolver_revision=(
                    RUNTIME_MODEL_PROFILE_RESOLVER_REVISION
                ),
                pydantic_ai_version=importlib.metadata.version("pydantic-ai-slim"),
                genai_prices_version=importlib.metadata.version("genai-prices"),
                projection_fingerprint=fingerprint,
            )
            async with self.session_manager() as session:
                catalog = await self.catalog_repository.ensure_system_catalog(
                    session,
                    provider=provider,
                    purpose=LLMCatalogPurpose.CONVERSATION,
                )
                candidate_id = await self.catalog_repository.create_candidate_snapshot(
                    session,
                    catalog=catalog,
                    entries=entries,
                    diagnostics={
                        "shadow": True,
                        "source_kind": source.source_kind,
                        "source_snapshot_id": source.id,
                        "projection_fingerprint": fingerprint,
                        "resolver_revision": (RUNTIME_MODEL_PROFILE_RESOLVER_REVISION),
                    },
                    provenance=provenance,
                    catalog_configuration_version=None,
                )
            visible_count = sum(
                entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
                for entry in entries
            )
            summaries.append(
                SystemCatalogShadowSummary(
                    provider=provider,
                    catalog_id=catalog.id,
                    candidate_snapshot_id=candidate_id,
                    visible_count=visible_count,
                    hidden_count=len(entries) - visible_count,
                    projection_fingerprint=fingerprint,
                )
            )
        return summaries


def project_system_shadow_entries(
    *,
    provider: LLMProvider,
    source: ModelMetadataSourceSnapshot,
) -> list[LLMCatalogEntryCreate]:
    """Project one system provider through the shared runtime resolver."""
    source_provider = _find_source_provider(source.payload, provider=provider)
    if source_provider is None:
        raise ModelMetadataProjectionError(
            f"The model metadata source is missing provider {provider.value}."
        )
    if not source_provider.models:
        raise ModelMetadataProjectionError(
            f"The model metadata source provider {provider.value} has no models."
        )
    return [
        _project_system_model(
            provider=provider,
            source_provider=source_provider,
            model=model,
            source=source,
        )
        for model in source_provider.models
    ]


def projection_fingerprint(
    *,
    provider: LLMProvider,
    source: ModelMetadataSourceSnapshot,
) -> str:
    """Fingerprint source, resolver, dependency, and projection policy authority."""
    value = {
        "provider": provider.value,
        "purpose": LLMCatalogPurpose.CONVERSATION.value,
        "source_snapshot_id": source.id,
        "source_hash": source.source_hash,
        "source_schema_version": source.source_schema_version,
        "genai_prices_version": importlib.metadata.version("genai-prices"),
        "pydantic_ai_version": importlib.metadata.version("pydantic-ai-slim"),
        "resolver_revision": RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
        "projection_schema_version": MODEL_METADATA_PROJECTION_SCHEMA_VERSION,
        "projection_policy_revision": MODEL_METADATA_PROJECTION_POLICY_REVISION,
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _find_source_provider(
    payload: ModelMetadataSourcePayload,
    *,
    provider: LLMProvider,
) -> SourceProviderRecord | None:
    source_provider_id = _SYSTEM_SOURCE_PROVIDERS.get(provider)
    if source_provider_id is None:
        raise ValueError("Provider does not have a system metadata source.")
    return next(
        (
            source_provider
            for source_provider in payload.providers
            if source_provider.id == source_provider_id
        ),
        None,
    )


def _project_system_model(
    *,
    provider: LLMProvider,
    source_provider: SourceProviderRecord,
    model: SourceModelRecord,
    source: ModelMetadataSourceSnapshot,
) -> LLMCatalogEntryCreate:
    hidden_reason = _hidden_reason(provider=provider, model=model)
    resolution = resolve_runtime_model_profile(
        provider=provider,
        model=model.id,
        profile_model=model.id,
        assembly_metadata=None,
        context_window=model.context_window,
        context_window_explicit=True,
        source_model=model,
    )
    visibility = (
        LLMCatalogEntryVisibility.HIDDEN
        if hidden_reason is not None
        else LLMCatalogEntryVisibility.SELECTABLE
    )
    return LLMCatalogEntryCreate(
        provider=provider,
        provider_model_identifier=model.id,
        display_name=model.name or model.id,
        normalized_capabilities=resolution.normalized_capabilities.model_dump(
            mode="json"
        ),
        supported_execution_options=(
            [option.value for option in _openai_supported_execution_options(model.id)]
            if provider is LLMProvider.OPENAI
            else []
        ),
        lifecycle_status=(
            LLMModelLifecycleStatus.DEPRECATED
            if model.deprecated is True
            else LLMModelLifecycleStatus.ACTIVE
        ),
        visibility_status=visibility,
        provider_integration_id=None,
        publisher=_developer(provider).value,
        family=_family(model.id),
        source_metadata={
            "source_kind": source.source_kind,
            "source_provider_id": source_provider.id,
            "source_model_id": model.id,
            "source_hash": source.source_hash,
            "context_window": model.context_window,
            "deprecated": model.deprecated,
        },
        projection_metadata={
            "shadow": True,
            "resolver_revision": resolution.resolver_revision,
            "freshness_rank": model_freshness_rank(model.id),
            "runtime_model_kind": resolution.model_kind,
            "native_protocol": resolution.protocol,
        },
        hidden_reason=hidden_reason,
    )


def _hidden_reason(
    *,
    provider: LLMProvider,
    model: SourceModelRecord,
) -> str | None:
    if model.deprecated is True:
        return "deprecated"
    identifier = model.id.lower()
    blocked_fragments = (
        "embedding",
        "moderation",
        "realtime",
        "transcribe",
        "transcription",
        "tts",
        "whisper",
        "image",
    )
    if any(fragment in identifier for fragment in blocked_fragments):
        return "unsupported_model_kind"
    match provider:
        case LLMProvider.OPENAI:
            if not identifier.startswith(("chatgpt-", "gpt-", "o1", "o3", "o4")):
                return "unsupported_model_family"
        case LLMProvider.ANTHROPIC:
            if not identifier.startswith("claude-"):
                return "unsupported_model_family"
        case LLMProvider.GOOGLE_GEMINI:
            if not identifier.startswith(("gemini-", "gemma-")):
                return "unsupported_model_family"
        case _:
            raise ValueError("Provider does not have a system metadata projection.")
    return None


def _developer(provider: LLMProvider) -> LLMModelDeveloper:
    match provider:
        case LLMProvider.OPENAI:
            return LLMModelDeveloper.OPENAI
        case LLMProvider.ANTHROPIC:
            return LLMModelDeveloper.ANTHROPIC
        case LLMProvider.GOOGLE_GEMINI:
            return LLMModelDeveloper.GOOGLE
        case _:
            raise ValueError("Provider does not have a system metadata projection.")


def _family(model_id: str) -> str:
    parts = model_id.split("-")
    if len(parts) >= 2 and parts[0] in {"claude", "gemini"}:
        return "-".join(parts[:2])
    return parts[0]
