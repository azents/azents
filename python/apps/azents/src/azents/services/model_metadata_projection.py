"""Replacement catalog projections from durable Pydantic ecosystem metadata."""

import dataclasses
import datetime
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
from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelParameterCapabilities,
    model_freshness_rank,
)
from azents.core.model_metadata_source import (
    ModelMetadataSourcePayload,
    SourceModelMatch,
    SourceModelRecord,
    SourceProviderRecord,
    lookup_source_model,
)
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.providers.model_profiles import (
    RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
    resolve_runtime_model_profile,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_catalog.data import (
    CatalogProjectionProvenance,
    CatalogSyncAlreadyRunning,
    LLMCatalogEntryCreate,
)
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot
from azents.services.model_listing.data import NormalizedModelCandidate
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
class SystemCatalogCandidateSummary:
    """One prepared non-current replacement candidate."""

    provider: LLMProvider
    catalog_id: str
    candidate_snapshot_id: str
    expected_current_snapshot_id: str | None
    visible_count: int
    hidden_count: int
    projection_fingerprint: str


@dataclasses.dataclass(frozen=True)
class SystemCatalogCutoverSummary:
    """One replacement system projection published as current authority."""

    provider: LLMProvider
    catalog_id: str
    snapshot_id: str | None
    visible_count: int
    hidden_count: int
    projection_fingerprint: str
    status: str = "succeeded"


class ModelMetadataProjectionError(RuntimeError):
    """Replacement metadata cannot produce a complete system projection."""


class _SystemCatalogPublicationBusy(RuntimeError):
    """One catalog in an atomic system publication set is already running."""


@dataclasses.dataclass(frozen=True)
class SystemCatalogReplacementProjectionService:
    """Prepare replacement system projections without changing current pointers."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    catalog_repository: Annotated[LLMCatalogRepository, Depends(LLMCatalogRepository)]
    source_sync_service: Annotated[
        ModelMetadataSourceSyncService, Depends(ModelMetadataSourceSyncService)
    ]

    async def prepare_candidates(self) -> list[SystemCatalogCandidateSummary]:
        """Refresh the replacement source and create non-current candidates."""
        source = await self.source_sync_service.sync_current_source()
        return await self._prepare_candidates(
            source=source,
            providers=tuple(_SYSTEM_SOURCE_PROVIDERS),
        )

    async def prepare_and_publish_cutover(
        self,
        *,
        provider: LLMProvider | None,
    ) -> list[SystemCatalogCutoverSummary]:
        """Refresh, prepare, and atomically publish replacement system catalogs."""
        if provider is not None and provider not in _SYSTEM_SOURCE_PROVIDERS:
            raise ValueError("Unsupported system catalog provider.")
        source = await self.source_sync_service.sync_current_source()
        providers = (
            (provider,) if provider is not None else tuple(_SYSTEM_SOURCE_PROVIDERS)
        )
        candidates = await self._prepare_candidates(
            source=source,
            providers=providers,
        )
        attempt_ids: dict[str, str] = {}
        try:
            async with self.session_manager() as session:
                for candidate in candidates:
                    attempt = await self.catalog_repository.begin_attempt(
                        session,
                        catalog_id=candidate.catalog_id,
                        source_key=source.source_key,
                        started_at=datetime.datetime.now(datetime.UTC),
                    )
                    if isinstance(attempt, CatalogSyncAlreadyRunning):
                        raise _SystemCatalogPublicationBusy
                    attempt_ids[candidate.catalog_id] = attempt
        except _SystemCatalogPublicationBusy:
            return [
                SystemCatalogCutoverSummary(
                    provider=candidate.provider,
                    catalog_id=candidate.catalog_id,
                    snapshot_id=None,
                    visible_count=0,
                    hidden_count=0,
                    projection_fingerprint=candidate.projection_fingerprint,
                    status="running",
                )
                for candidate in candidates
            ]

        snapshot_ids: dict[str, str] = {}
        try:
            async with self.session_manager() as session:
                for candidate in candidates:
                    latest_attempt_id = await (
                        self.catalog_repository.lock_catalog_for_attempt_completion
                    )(
                        session,
                        catalog_id=candidate.catalog_id,
                    )
                    if latest_attempt_id != attempt_ids[candidate.catalog_id]:
                        raise RuntimeError("The system catalog refresh was superseded.")
                    snapshot_ids[
                        candidate.catalog_id
                    ] = await self.catalog_repository.publish_candidate_snapshot(
                        session,
                        catalog_id=candidate.catalog_id,
                        candidate_snapshot_id=candidate.candidate_snapshot_id,
                        expected_current_snapshot_id=(
                            candidate.expected_current_snapshot_id
                        ),
                        expected_catalog_configuration_version=None,
                        expected_projection_fingerprint=(
                            candidate.projection_fingerprint
                        ),
                        expected_source_key=source.source_key,
                        expected_source_snapshot_id=source.id,
                        fence_latest_attempt=True,
                        expected_latest_attempt_id=attempt_ids[candidate.catalog_id],
                    )
                for candidate in candidates:
                    await self.catalog_repository.mark_attempt_succeeded(
                        session,
                        attempt_id=attempt_ids[candidate.catalog_id],
                        finished_at=datetime.datetime.now(datetime.UTC),
                        produced_snapshot_id=snapshot_ids[candidate.catalog_id],
                        fetched_count=source.model_count,
                        matched_count=(
                            candidate.visible_count + candidate.hidden_count
                        ),
                        skipped_count=0,
                        hidden_count=candidate.hidden_count,
                        diagnostics={
                            "provider": candidate.provider.value,
                            "source_snapshot_id": source.id,
                            "projection_fingerprint": (
                                candidate.projection_fingerprint
                            ),
                        },
                    )
        except Exception as error:
            async with self.session_manager() as session:
                for candidate in candidates:
                    await self.catalog_repository.mark_attempt_failed(
                        session,
                        attempt_id=attempt_ids[candidate.catalog_id],
                        finished_at=datetime.datetime.now(datetime.UTC),
                        failure_code=type(error).__name__,
                        failure_message=str(error),
                        action_hint=(
                            "Check replacement source and projection readiness."
                        ),
                        diagnostics={
                            "provider": candidate.provider.value,
                            "source_snapshot_id": source.id,
                            "projection_fingerprint": (
                                candidate.projection_fingerprint
                            ),
                        },
                    )
            raise

        return [
            SystemCatalogCutoverSummary(
                provider=candidate.provider,
                catalog_id=candidate.catalog_id,
                snapshot_id=snapshot_ids[candidate.catalog_id],
                visible_count=candidate.visible_count,
                hidden_count=candidate.hidden_count,
                projection_fingerprint=candidate.projection_fingerprint,
            )
            for candidate in candidates
        ]

    async def _prepare_candidates(
        self,
        *,
        source: ModelMetadataSourceSnapshot,
        providers: tuple[LLMProvider, ...],
    ) -> list[SystemCatalogCandidateSummary]:
        """Create complete candidates for one captured source."""
        projections = [
            (
                provider,
                project_system_entries(
                    provider=provider,
                    source=source,
                ),
                projection_fingerprint(
                    provider=provider,
                    source=source,
                ),
            )
            for provider in providers
        ]
        summaries: list[SystemCatalogCandidateSummary] = []
        for provider, entries, fingerprint in projections:
            provenance = CatalogProjectionProvenance(
                source_snapshot_id=source.id,
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
                SystemCatalogCandidateSummary(
                    provider=provider,
                    catalog_id=catalog.id,
                    candidate_snapshot_id=candidate_id,
                    expected_current_snapshot_id=catalog.current_snapshot_id,
                    visible_count=visible_count,
                    hidden_count=len(entries) - visible_count,
                    projection_fingerprint=fingerprint,
                )
            )
        return summaries


def project_system_entries(
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


def project_integration_replacement_entries(
    *,
    integration_id: str,
    provider: LLMProvider,
    candidates: list[NormalizedModelCandidate],
    source: ModelMetadataSourceSnapshot | None,
    provider_listing_source: str,
) -> list[LLMCatalogEntryCreate]:
    """Project provider-visible models without making source matching a gate."""
    entries: list[LLMCatalogEntryCreate] = []
    for candidate in candidates:
        source_match = (
            lookup_source_model(
                source.payload,
                provider=provider,
                model_identifier=candidate.model_identifier,
            )
            if source is not None
            else None
        )
        source_model = source_match.model if source_match is not None else None
        resolution = resolve_runtime_model_profile(
            provider=provider,
            model=candidate.model_identifier,
            profile_model=candidate.model_identifier,
            assembly_metadata=ModelAssemblyMetadata(
                model_developer=candidate.model_developer,
                model_family=candidate.model_family,
                capabilities=candidate.normalized_capabilities,
            ),
            context_window=(
                source_model.context_window if source_model is not None else None
            ),
            context_window_explicit=source_model is not None,
            source_model=source_model,
        )
        capabilities = _merge_provider_listing_capabilities(
            candidate=candidate,
            resolved=resolution.normalized_capabilities,
            source_match=source_match,
        )
        entries.append(
            LLMCatalogEntryCreate(
                provider=provider,
                provider_model_identifier=candidate.model_identifier,
                display_name=candidate.model_display_name,
                normalized_capabilities=capabilities.model_dump(mode="json"),
                supported_execution_options=[
                    option.value for option in candidate.supported_execution_options
                ],
                lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
                visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
                provider_integration_id=integration_id,
                publisher=candidate.model_developer.value,
                family=candidate.model_family,
                source_metadata={
                    "source_kind": source.source_kind if source is not None else None,
                    "source_snapshot_id": source.id if source is not None else None,
                    "source_hash": source.source_hash if source is not None else None,
                    "source_provider_id": (
                        source_match.provider.id if source_match is not None else None
                    ),
                    "source_model_id": (
                        source_match.model.id if source_match is not None else None
                    ),
                    "provider_listing_source": provider_listing_source,
                    "provider_metadata": candidate.source_metadata,
                },
                projection_metadata={
                    "matched": source_match is not None,
                    "resolver_revision": resolution.resolver_revision,
                    "runtime_model_kind": resolution.model_kind,
                    "native_protocol": resolution.protocol,
                    "freshness_rank": model_freshness_rank(candidate.model_identifier),
                },
                hidden_reason=None,
            )
        )
    return entries


def _merge_provider_listing_capabilities(
    *,
    candidate: NormalizedModelCandidate,
    resolved: ModelCapabilities,
    source_match: SourceModelMatch | None,
) -> ModelCapabilities:
    """Intersect provider-visible evidence with shared runtime compatibility."""
    runtime = resolved
    listing = candidate.normalized_capabilities
    merged = runtime.model_copy(deep=True)
    if listing.context_window.default_input_tokens is not None:
        merged.context_window.default_input_tokens = (
            listing.context_window.default_input_tokens
        )
    if listing.context_window.max_input_tokens is not None:
        merged.context_window.max_input_tokens = listing.context_window.max_input_tokens
    elif source_match is not None:
        merged.context_window.max_input_tokens = source_match.model.context_window
    merged.context_window.max_output_tokens = listing.context_window.max_output_tokens
    if listing.modalities.input:
        merged.modalities.input = [
            modality
            for modality in merged.modalities.input
            if modality in listing.modalities.input
        ]
    if listing.modalities.output:
        merged.modalities.output = [
            modality
            for modality in merged.modalities.output
            if modality in listing.modalities.output
        ]
    merged.tool_calling.supported = (
        merged.tool_calling.supported and listing.tool_calling.supported
    )
    if listing.tool_calling.parallel_tool_calls is not None:
        merged.tool_calling.parallel_tool_calls = (
            listing.tool_calling.parallel_tool_calls
            if merged.tool_calling.supported
            else False
        )
    if listing.tool_calling.strict_json_schema is not None:
        merged.tool_calling.strict_json_schema = (
            listing.tool_calling.strict_json_schema
            and merged.tool_calling.strict_json_schema is True
        )
    merged.reasoning.supported = (
        merged.reasoning.supported and listing.reasoning.supported
    )
    if listing.reasoning.effort_levels:
        merged.reasoning.effort_levels = [
            effort
            for effort in merged.reasoning.effort_levels
            if effort in listing.reasoning.effort_levels
        ]
    elif not merged.reasoning.supported:
        merged.reasoning.effort_levels = []
    merged.reasoning.summaries = listing.reasoning.summaries
    merged.built_in_tools.supported = [
        tool
        for tool in merged.built_in_tools.supported
        if tool in listing.built_in_tools.supported
    ]
    merged.parameters = ModelParameterCapabilities(
        temperature=(merged.parameters.temperature and listing.parameters.temperature),
        max_output_tokens=(
            merged.parameters.max_output_tokens and listing.parameters.max_output_tokens
        ),
        top_p=merged.parameters.top_p and listing.parameters.top_p,
        top_k=merged.parameters.top_k and listing.parameters.top_k,
        stop_sequences=(
            merged.parameters.stop_sequences and listing.parameters.stop_sequences
        ),
    )
    if listing.compatibility.provider_family is not None:
        merged.compatibility.provider_family = listing.compatibility.provider_family
    if listing.compatibility.responses_api is not None:
        merged.compatibility.responses_api = listing.compatibility.responses_api
    if listing.compatibility.unsupported_media_policy is not None:
        merged.compatibility.unsupported_media_policy = (
            listing.compatibility.unsupported_media_policy
        )
    return merged


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


def integration_projection_fingerprint(
    *,
    provider: LLMProvider,
    source: ModelMetadataSourceSnapshot | None,
    entries: list[LLMCatalogEntryCreate],
    catalog_configuration_version: int,
) -> str:
    """Fingerprint the complete persisted replacement projection inputs."""
    value = {
        "provider": provider.value,
        "purpose": LLMCatalogPurpose.CONVERSATION.value,
        "source_snapshot_id": source.id if source is not None else None,
        "source_hash": source.source_hash if source is not None else None,
        "source_schema_version": (
            source.source_schema_version if source is not None else None
        ),
        "genai_prices_version": importlib.metadata.version("genai-prices"),
        "pydantic_ai_version": importlib.metadata.version("pydantic-ai-slim"),
        "resolver_revision": RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
        "projection_schema_version": MODEL_METADATA_PROJECTION_SCHEMA_VERSION,
        "projection_policy_revision": MODEL_METADATA_PROJECTION_POLICY_REVISION,
        "catalog_configuration_version": catalog_configuration_version,
        "entries": [
            {
                "provider": entry.provider.value,
                "model_identifier": entry.provider_model_identifier,
                "display_name": entry.display_name,
                "capabilities": entry.normalized_capabilities,
                "execution_options": entry.supported_execution_options,
                "lifecycle_status": entry.lifecycle_status.value,
                "visibility_status": entry.visibility_status.value,
                "provider_integration_id": entry.provider_integration_id,
                "publisher": entry.publisher,
                "family": entry.family,
                "source_metadata": entry.source_metadata,
                "projection_metadata": entry.projection_metadata,
                "hidden_reason": entry.hidden_reason,
            }
            for entry in sorted(
                entries,
                key=lambda entry: (
                    entry.provider.value,
                    entry.provider_model_identifier,
                    entry.provider_integration_id or "",
                ),
            )
        ],
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
            "projection_mode": "replacement",
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
