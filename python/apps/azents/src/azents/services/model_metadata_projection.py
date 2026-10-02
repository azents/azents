"""Stored conversation catalog projections from captured data-only evidence."""

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
from azents.core.llm_catalog import model_freshness_rank
from azents.core.model_capability_projection import (
    CAPABILITY_PROJECTION_REVISION,
    project_capabilities,
)
from azents.core.model_catalog_identity import system_catalog_models
from azents.core.model_catalog_source import CatalogSourceModel
from azents.engine.providers.model_profiles import (
    RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
    protocol_for_provider,
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
from azents.services.model_listing.providers import _openai_supported_execution_options
from azents.services.model_metadata import ModelMetadataService
from azents.services.model_metadata_source import ModelMetadataSourceSyncService

MODEL_METADATA_PROJECTION_SCHEMA_VERSION = "2"
MODEL_METADATA_PROJECTION_POLICY_REVISION = "3"
_SYSTEM_PROVIDERS = (
    LLMProvider.OPENAI,
    LLMProvider.ANTHROPIC,
    LLMProvider.GOOGLE_GEMINI,
)


@dataclasses.dataclass(frozen=True)
class SystemCatalogCandidateSummary:
    """One complete replacement projection awaiting atomic publication."""

    provider: LLMProvider
    catalog_id: str
    candidate_snapshot_id: str
    expected_current_snapshot_id: str | None
    visible_count: int
    hidden_count: int
    projection_fingerprint: str


@dataclasses.dataclass(frozen=True)
class SystemCatalogCutoverSummary:
    """Result of an existing scheduled or administrator publication operation."""

    provider: LLMProvider
    catalog_id: str
    snapshot_id: str | None
    visible_count: int
    hidden_count: int
    projection_fingerprint: str
    status: str = "succeeded"


class ModelMetadataProjectionError(RuntimeError):
    """Source evidence cannot produce a complete system projection."""


class _SystemCatalogPublicationBusy(RuntimeError):
    """One catalog in an atomic system publication set is already running."""


@dataclasses.dataclass(frozen=True)
class SystemCatalogReplacementProjectionService:
    """Refresh and publish stored catalogs through the established lifecycle."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    catalog_repository: Annotated[LLMCatalogRepository, Depends(LLMCatalogRepository)]
    source_sync_service: Annotated[
        ModelMetadataSourceSyncService, Depends(ModelMetadataSourceSyncService)
    ]

    async def prepare_candidates(self) -> list[SystemCatalogCandidateSummary]:
        """Create non-current candidates within the existing refresh operation."""
        source = await self.source_sync_service.sync_current_source()
        return await self._prepare_candidates(
            source=source, providers=_SYSTEM_PROVIDERS
        )

    async def prepare_and_publish_cutover(
        self, *, provider: LLMProvider | None
    ) -> list[SystemCatalogCutoverSummary]:
        """Collect and atomically publish through existing system refresh ownership."""
        if provider is not None and provider not in _SYSTEM_PROVIDERS:
            raise ValueError("Unsupported system catalog provider.")
        source = await self.source_sync_service.sync_current_source()
        providers = (provider,) if provider is not None else _SYSTEM_PROVIDERS
        candidates = await self._prepare_candidates(source=source, providers=providers)
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
                    provider=item.provider,
                    catalog_id=item.catalog_id,
                    snapshot_id=None,
                    visible_count=item.visible_count,
                    hidden_count=item.hidden_count,
                    projection_fingerprint=item.projection_fingerprint,
                    status="running",
                )
                for item in candidates
            ]
        snapshot_ids: dict[str, str] = {}
        try:
            async with self.session_manager() as session:
                for candidate in candidates:
                    latest = await (
                        self.catalog_repository.lock_catalog_for_attempt_completion
                    )(session, catalog_id=candidate.catalog_id)
                    if latest != attempt_ids[candidate.catalog_id]:
                        raise RuntimeError("The system catalog refresh was superseded.")
                    snapshot_ids[
                        candidate.catalog_id
                    ] = await self.catalog_repository.publish_candidate_snapshot(
                        session,
                        catalog_id=candidate.catalog_id,
                        candidate_snapshot_id=candidate.candidate_snapshot_id,
                        expected_current_snapshot_id=candidate.expected_current_snapshot_id,
                        expected_catalog_configuration_version=None,
                        expected_projection_fingerprint=candidate.projection_fingerprint,
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
                        matched_count=candidate.visible_count + candidate.hidden_count,
                        skipped_count=0,
                        hidden_count=candidate.hidden_count,
                        diagnostics={
                            "provider": candidate.provider.value,
                            "source_snapshot_id": source.id,
                            "projection_fingerprint": candidate.projection_fingerprint,
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
                            "projection_fingerprint": candidate.projection_fingerprint,
                        },
                    )
            raise
        return [
            SystemCatalogCutoverSummary(
                provider=item.provider,
                catalog_id=item.catalog_id,
                snapshot_id=snapshot_ids[item.catalog_id],
                visible_count=item.visible_count,
                hidden_count=item.hidden_count,
                projection_fingerprint=item.projection_fingerprint,
            )
            for item in candidates
        ]

    async def _prepare_candidates(
        self, *, source: ModelMetadataSourceSnapshot, providers: tuple[LLMProvider, ...]
    ) -> list[SystemCatalogCandidateSummary]:
        """Capture one lifecycle date for projection and fingerprint together."""
        effective_date = datetime.datetime.now(datetime.UTC).date()
        projections = [
            (
                provider,
                project_system_entries(
                    provider=provider, source=source, effective_date=effective_date
                ),
                projection_fingerprint(
                    provider=provider, source=source, effective_date=effective_date
                ),
            )
            for provider in providers
        ]
        summaries: list[SystemCatalogCandidateSummary] = []
        for provider, entries, fingerprint in projections:
            provenance = CatalogProjectionProvenance(
                source_snapshot_id=source.id,
                projection_schema_version=MODEL_METADATA_PROJECTION_SCHEMA_VERSION,
                runtime_profile_resolver_revision=RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
                pydantic_ai_version=_adapter_version(provider),
                genai_prices_version=None,
                projection_fingerprint=fingerprint,
            )
            async with self.session_manager() as session:
                catalog = await self.catalog_repository.ensure_system_catalog(
                    session, provider=provider, purpose=LLMCatalogPurpose.CONVERSATION
                )
                candidate_id = await self.catalog_repository.create_candidate_snapshot(
                    session,
                    catalog=catalog,
                    entries=entries,
                    diagnostics={
                        "source_kind": source.source_kind,
                        "source_snapshot_id": source.id,
                        "projection_fingerprint": fingerprint,
                        "resolver_revision": RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
                        "effective_date": effective_date.isoformat(),
                    },
                    provenance=provenance,
                    catalog_configuration_version=None,
                )
            visible = sum(
                entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
                for entry in entries
            )
            summaries.append(
                SystemCatalogCandidateSummary(
                    provider=provider,
                    catalog_id=catalog.id,
                    candidate_snapshot_id=candidate_id,
                    expected_current_snapshot_id=catalog.current_snapshot_id,
                    visible_count=visible,
                    hidden_count=len(entries) - visible,
                    projection_fingerprint=fingerprint,
                )
            )
        return summaries


def project_system_entries(
    *,
    provider: LLMProvider,
    source: ModelMetadataSourceSnapshot,
    effective_date: datetime.date,
) -> list[LLMCatalogEntryCreate]:
    """Project source-owned system inventory without price or name capability gates."""
    if provider not in _SYSTEM_PROVIDERS:
        raise ValueError("Provider does not have a system metadata source.")
    models = system_catalog_models(source.payload, provider=provider)
    if not models:
        raise ModelMetadataProjectionError(
            f"The model metadata source is missing provider {provider.value}."
        )
    return [
        _project_system_model(
            provider=provider,
            identifier=item.execution_model_identifier,
            model=item.source_model,
            source=source,
            effective_date=effective_date,
        )
        for item in models
    ]


def project_integration_replacement_entries(
    *,
    integration_id: str,
    provider: LLMProvider,
    candidates: list[NormalizedModelCandidate],
    source: ModelMetadataSourceSnapshot | None,
    provider_listing_source: str,
) -> list[LLMCatalogEntryCreate]:
    """Publish every valid provider-visible identifier with presence-aware facts."""
    entries: list[LLMCatalogEntryCreate] = []
    for candidate in candidates:
        source_model = ModelMetadataService.lookup(
            source, provider=provider, model_identifier=candidate.model_identifier
        )
        capabilities = project_capabilities(
            provider=provider,
            exact_model=candidate.model_identifier,
            source_model=source_model,
            evidence=candidate.capability_evidence,
            model_developer=candidate.model_developer,
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
                    "source_kind": source.source_kind if source else None,
                    "source_snapshot_id": source.id if source else None,
                    "source_hash": source.source_hash if source else None,
                    "source_provider_id": source_model.provider
                    if source_model
                    else None,
                    "source_model_id": source_model.source_key
                    if source_model
                    else None,
                    "provider_listing_source": provider_listing_source,
                    "provider_metadata": candidate.source_metadata,
                    "capability_evidence": (
                        candidate.capability_evidence.model_dump(mode="json")
                        if candidate.capability_evidence is not None
                        else None
                    ),
                },
                projection_metadata={
                    "matched": source_model is not None,
                    "resolver_revision": RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
                    "capability_projection_revision": CAPABILITY_PROJECTION_REVISION,
                    "native_protocol": protocol_for_provider(
                        provider=provider, model=candidate.model_identifier
                    ),
                    "freshness_rank": model_freshness_rank(candidate.model_identifier),
                    "diagnostics": list(source_model.reasoning.diagnostics)
                    if source_model
                    else [],
                },
                hidden_reason=None,
            )
        )
    return entries


def _adapter_version(provider: LLMProvider) -> str | None:
    return (
        None
        if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}
        else importlib.metadata.version("pydantic-ai-slim")
    )


def _fingerprint(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def projection_fingerprint(
    *,
    provider: LLMProvider,
    source: ModelMetadataSourceSnapshot,
    effective_date: datetime.date,
) -> str:
    """Fingerprint all source, interpreter, transport and lifecycle inputs."""
    return _fingerprint(
        {
            "provider": provider.value,
            "purpose": LLMCatalogPurpose.CONVERSATION.value,
            "source_snapshot_id": source.id,
            "source_hash": source.source_hash,
            "source_kind": source.source_kind,
            "source_schema_version": source.source_schema_version,
            "source_interpreter_revision": source.payload.interpreter_version,
            "pydantic_ai_version": _adapter_version(provider),
            "resolver_revision": RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
            "capability_projection_revision": CAPABILITY_PROJECTION_REVISION,
            "projection_schema_version": MODEL_METADATA_PROJECTION_SCHEMA_VERSION,
            "projection_policy_revision": MODEL_METADATA_PROJECTION_POLICY_REVISION,
            "effective_date": effective_date.isoformat(),
        }
    )


def integration_projection_fingerprint(
    *,
    provider: LLMProvider,
    source: ModelMetadataSourceSnapshot | None,
    entries: list[LLMCatalogEntryCreate],
    catalog_configuration_version: int,
) -> str:
    """Fingerprint complete persisted facts rather than sparse normalized defaults."""
    return _fingerprint(
        {
            "provider": provider.value,
            "purpose": LLMCatalogPurpose.CONVERSATION.value,
            "source_snapshot_id": source.id if source else None,
            "source_hash": source.source_hash if source else None,
            "source_kind": source.source_kind if source else None,
            "source_schema_version": source.source_schema_version if source else None,
            "source_interpreter_revision": source.payload.interpreter_version
            if source
            else None,
            "pydantic_ai_version": _adapter_version(provider),
            "resolver_revision": RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
            "capability_projection_revision": CAPABILITY_PROJECTION_REVISION,
            "projection_schema_version": MODEL_METADATA_PROJECTION_SCHEMA_VERSION,
            "projection_policy_revision": MODEL_METADATA_PROJECTION_POLICY_REVISION,
            "catalog_configuration_version": catalog_configuration_version,
            "entries": [
                dataclasses.asdict(entry)
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
    )


def _project_system_model(
    *,
    provider: LLMProvider,
    identifier: str,
    model: CatalogSourceModel,
    source: ModelMetadataSourceSnapshot,
    effective_date: datetime.date,
) -> LLMCatalogEntryCreate:
    deprecated = False
    if model.facts.deprecation_date.value is not None:
        try:
            deprecated = (
                datetime.date.fromisoformat(model.facts.deprecation_date.value)
                <= effective_date
            )
        except ValueError as error:
            raise ModelMetadataProjectionError(
                "The source deprecation date is invalid."
            ) from error
    hidden_reason = _hidden_reason(
        provider=provider, model=model, deprecated=deprecated
    )
    capabilities = project_capabilities(
        provider=provider,
        exact_model=identifier,
        source_model=model,
        evidence=None,
        model_developer=_developer(provider),
    )
    return LLMCatalogEntryCreate(
        provider=provider,
        provider_model_identifier=identifier,
        display_name=model.facts.display_name.value or identifier,
        normalized_capabilities=capabilities.model_dump(mode="json"),
        supported_execution_options=(
            [option.value for option in _openai_supported_execution_options(identifier)]
            if provider == LLMProvider.OPENAI
            else []
        ),
        lifecycle_status=LLMModelLifecycleStatus.DEPRECATED
        if deprecated
        else LLMModelLifecycleStatus.ACTIVE,
        visibility_status=LLMCatalogEntryVisibility.HIDDEN
        if hidden_reason
        else LLMCatalogEntryVisibility.SELECTABLE,
        provider_integration_id=None,
        publisher=_developer(provider).value,
        family=None,
        source_metadata={
            "source_kind": source.source_kind,
            "source_provider_id": model.provider,
            "source_model_id": model.source_key,
            "source_hash": source.source_hash,
            "deprecation_date": model.facts.deprecation_date.value,
            "facts": model.facts.model_dump(mode="json"),
        },
        projection_metadata={
            "projection_mode": "replacement",
            "resolver_revision": RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
            "capability_projection_revision": CAPABILITY_PROJECTION_REVISION,
            "freshness_rank": model_freshness_rank(identifier),
            "native_protocol": protocol_for_provider(
                provider=provider, model=identifier
            ),
            "effective_date": effective_date.isoformat(),
            "diagnostics": list(model.reasoning.diagnostics),
        },
        hidden_reason=hidden_reason,
    )


def _hidden_reason(
    *, provider: LLMProvider, model: CatalogSourceModel, deprecated: bool
) -> str | None:
    if deprecated:
        return "deprecated"
    facts = model.facts
    if facts.mode.value not in {"chat", "responses"}:
        return (
            "unsupported_model_kind"
            if facts.mode.state == "value"
            else "conversation_support_unknown"
        )
    if facts.output_modalities.state == "value" and "text" not in (
        facts.output_modalities.value or ()
    ):
        return "unsupported_output_modality"
    if (
        provider == LLMProvider.OPENAI
        and facts.supported_endpoints.state == "value"
        and "/v1/responses" not in (facts.supported_endpoints.value or ())
    ):
        return "unsupported_endpoint"
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
