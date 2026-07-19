"""LLM catalog sync services."""

import dataclasses
import datetime
import hashlib
import json
import re
from typing import Annotated, Any, assert_never

import litellm
from azcommon.result import Failure, Result, Success
from fastapi import Depends
from litellm.types.utils import ProviderSpecificModelInfo
from pydantic import BaseModel, Field, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import AgentModelSelection, AgentModelSelectionInput
from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMCatalogLowererTarget,
    LLMCatalogScope,
    LLMModelDeveloper,
    LLMModelLifecycleStatus,
    LLMProvider,
)
from azents.core.llm_catalog import (
    INTEGRATION_SCOPED_CATALOG_PROVIDERS,
    ModelBuiltInToolCapabilities,
    ModelCapabilities,
    ModelCompatibilityCapabilities,
    ModelContextWindow,
    ModelModalities,
    ModelModality,
    ModelReasoningCapabilities,
    ModelReasoningEffort,
    ModelToolCallingCapabilities,
)
from azents.core.llm_catalog_sync import (
    CatalogSyncAttemptState,
    IntegrationCatalogSyncDenialReason,
    IntegrationCatalogSyncPolicyDecision,
    IntegrationCatalogSyncPolicyInput,
    IntegrationCatalogSyncTrigger,
    evaluate_integration_catalog_sync_policy,
)
from azents.core.llm_mapping import to_runtime_model
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import (
    LiteLLMSourceSnapshotRepository,
    LLMCatalogRepository,
)
from azents.repos.llm_catalog.data import (
    CatalogNotFound,
    CatalogSyncAlreadyRunning,
    LiteLLMSourceSnapshot,
    LLMCatalogEntry,
    LLMCatalogEntryCreate,
    LLMCatalogSyncAttempt,
)
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.services.builtin_capabilities import supported_builtin_capabilities
from azents.services.chatgpt_oauth.data import ProviderRejected, ProviderUnavailable
from azents.services.chatgpt_oauth.runtime import ensure_runtime_tokens
from azents.services.model_listing.data import ModelListingOutput
from azents.services.model_listing.providers import (
    ListingProviderError,
    list_bedrock_models_for_integration,
    list_chatgpt_models_for_integration,
    list_openrouter_models_for_integration,
    list_vertex_models_for_integration,
)
from azents.testing.deterministic_model_listing import (
    build_deterministic_listing,
    parse_deterministic_fixture_variant,
)

_LITELLM_SOURCE_KEY = "litellm_model_cost"
_LITELLM_SOURCE_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
_PROVIDER_MODEL_INFO_ADAPTER = TypeAdapter(ProviderSpecificModelInfo)


def _get_integration_repository(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> LLMProviderIntegrationRepository:
    """LLMProviderIntegrationRepository dependency."""
    return LLMProviderIntegrationRepository(cipher=cipher)


_SYSTEM_PROVIDER_TO_LITELLM_PROVIDER: dict[LLMProvider, tuple[str, ...]] = {
    LLMProvider.OPENAI: ("openai",),
    LLMProvider.XAI: ("xai",),
    LLMProvider.XAI_OAUTH: ("xai",),
    LLMProvider.ANTHROPIC: ("anthropic",),
    LLMProvider.GOOGLE_GEMINI: ("gemini",),
}

_PROVIDER_TO_DEVELOPER: dict[LLMProvider, LLMModelDeveloper] = {
    LLMProvider.OPENAI: LLMModelDeveloper.OPENAI,
    LLMProvider.CHATGPT_OAUTH: LLMModelDeveloper.OPENAI,
    LLMProvider.XAI: LLMModelDeveloper.XAI,
    LLMProvider.XAI_OAUTH: LLMModelDeveloper.XAI,
    LLMProvider.OPENROUTER: LLMModelDeveloper.OTHER,
    LLMProvider.ANTHROPIC: LLMModelDeveloper.ANTHROPIC,
    LLMProvider.GOOGLE_GEMINI: LLMModelDeveloper.GOOGLE,
    LLMProvider.GOOGLE_VERTEX_AI: LLMModelDeveloper.GOOGLE,
}


def _developer_from_entry(entry: LLMCatalogEntry) -> LLMModelDeveloper:
    """Resolve Agent snapshot developer from catalog projection."""
    candidates = [
        entry.publisher,
        entry.family,
        entry.provider_model_identifier,
        entry.runtime_model_identifier,
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        lowered = candidate.lower()
        for developer in LLMModelDeveloper:
            if developer.value in lowered:
                return developer
    return _PROVIDER_TO_DEVELOPER.get(entry.provider, LLMModelDeveloper.OTHER)


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogSyncNotFound:
    """Integration catalog sync target not found."""

    integration_id: str


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogSyncUnsupportedProvider:
    """Integration provider is not supported by projection sync."""

    provider: LLMProvider


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogSyncAlreadyRunning:
    """Integration catalog sync is already running."""

    catalog_id: str
    attempt_id: str


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogSyncSuperseded:
    """Integration catalog sync was superseded before it could publish."""

    catalog_id: str
    superseding_attempt_id: str


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogSyncThrottled:
    """Integration catalog sync is temporarily throttled."""

    retry_at: datetime.datetime


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogAutomaticRetryBlocked:
    """Automatic retry is blocked until explicit retry or configuration change."""

    pass


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogSyncNotStale:
    """Stale refresh was requested for a fresh catalog."""

    pass


def _sync_policy_failure(
    catalog_id: str,
    decision: IntegrationCatalogSyncPolicyDecision,
) -> (
    IntegrationCatalogSyncAlreadyRunning
    | IntegrationCatalogSyncThrottled
    | IntegrationCatalogAutomaticRetryBlocked
    | IntegrationCatalogSyncNotStale
):
    """Convert a synchronization policy denial to a service error."""
    match decision.denial_reason:
        case IntegrationCatalogSyncDenialReason.ALREADY_RUNNING:
            if decision.retry_at is None:
                raise RuntimeError("Running sync policy did not provide an expiry.")
            if decision.blocking_attempt_id is None:
                raise RuntimeError("Running sync policy did not identify the attempt.")
            return IntegrationCatalogSyncAlreadyRunning(
                catalog_id=catalog_id,
                attempt_id=decision.blocking_attempt_id,
            )
        case IntegrationCatalogSyncDenialReason.THROTTLED:
            if decision.retry_at is None:
                raise RuntimeError("Throttled sync policy did not provide retry time.")
            return IntegrationCatalogSyncThrottled(retry_at=decision.retry_at)
        case IntegrationCatalogSyncDenialReason.AUTOMATIC_RETRY_BLOCKED:
            return IntegrationCatalogAutomaticRetryBlocked()
        case IntegrationCatalogSyncDenialReason.NOT_STALE:
            return IntegrationCatalogSyncNotStale()
        case None:
            raise RuntimeError("Allowed sync policy decision cannot be a failure.")
        case _:
            assert_never(decision.denial_reason)


@dataclasses.dataclass(frozen=True)
class SystemCatalogProjectionSummary:
    """System/integration catalog projection summary."""

    provider: LLMProvider
    catalog_id: str
    snapshot_id: str | None
    visible_count: int
    hidden_count: int
    status: str = "succeeded"
    failure_code: str | None = None
    failure_message: str | None = None
    action_hint: str | None = None


class ModelCatalogEntryOutput(BaseModel):
    """Projected model catalog entry output."""

    id: str = Field(description="Catalog entry ID")
    provider: LLMProvider = Field(description="Hosting provider")
    provider_model_identifier: str = Field(description="Provider model identifier")
    lowerer_target: LLMCatalogLowererTarget = Field(description="Lowerer target")
    runtime_model_identifier: str = Field(description="Runtime model identifier")
    display_name: str = Field(description="Display name")
    normalized_capabilities: ModelCapabilities = Field(
        description="Normalized capability contract"
    )
    lifecycle_status: LLMModelLifecycleStatus = Field(description="Lifecycle status")
    visibility_status: LLMCatalogEntryVisibility = Field(description="Visibility state")
    publisher: str | None = Field(description="Publisher/developer identifier")
    family: str | None = Field(description="Model family")
    source_metadata: dict[str, Any] | None = Field(description="Source metadata")
    projection_metadata: dict[str, Any] | None = Field(
        description="Projection diagnostics"
    )

    @classmethod
    def convert_from(cls, entry: LLMCatalogEntry) -> "ModelCatalogEntryOutput":
        """Convert repository data to service output."""
        return cls(
            id=entry.id,
            provider=entry.provider,
            provider_model_identifier=entry.provider_model_identifier,
            lowerer_target=entry.lowerer_target,
            runtime_model_identifier=entry.runtime_model_identifier,
            display_name=entry.display_name,
            normalized_capabilities=ModelCapabilities.model_validate(
                entry.normalized_capabilities
            ),
            lifecycle_status=entry.lifecycle_status,
            visibility_status=entry.visibility_status,
            publisher=entry.publisher,
            family=entry.family,
            source_metadata=entry.source_metadata,
            projection_metadata=entry.projection_metadata,
        )


class ModelCatalogSyncAttemptOutput(BaseModel):
    """Latest catalog sync attempt output."""

    id: str = Field(description="Attempt ID")
    status: str = Field(description="Attempt status")
    started_at: datetime.datetime = Field(description="Attempt start time")
    finished_at: datetime.datetime | None = Field(description="Attempt finish time")
    failure_code: str | None = Field(description="Failure code")
    failure_message: str | None = Field(description="Failure message")
    action_hint: str | None = Field(description="Failure action hint")
    fetched_count: int = Field(description="Fetched source count")
    matched_count: int = Field(description="Matched entry count")
    skipped_count: int = Field(description="Skipped entry count")
    hidden_count: int = Field(description="Hidden entry count")

    @classmethod
    def convert_from(
        cls,
        attempt: LLMCatalogSyncAttempt,
    ) -> "ModelCatalogSyncAttemptOutput":
        """Convert repository data to service output."""
        return cls(
            id=attempt.id,
            status=attempt.status.value,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
            failure_code=attempt.failure_code,
            failure_message=attempt.failure_message,
            action_hint=attempt.action_hint,
            fetched_count=attempt.fetched_count,
            matched_count=attempt.matched_count,
            skipped_count=attempt.skipped_count,
            hidden_count=attempt.hidden_count,
        )


class SystemCatalogListItem(BaseModel):
    """System catalog list item."""

    provider: LLMProvider
    catalog_id: str | None = Field(description="Catalog ID")
    snapshot_id: str | None = Field(description="Current snapshot ID")
    visible_count: int = Field(description="Current visible entry count")
    hidden_count: int = Field(description="Current hidden entry count")
    latest_attempt: ModelCatalogSyncAttemptOutput | None = Field(
        description="Latest sync attempt"
    )


class ModelCatalogEntryListOutput(BaseModel):
    """Catalog entry list output."""

    catalog_id: str = Field(description="Catalog ID")
    catalog_scope: LLMCatalogScope = Field(description="Catalog ownership scope")
    current_snapshot_id: str | None = Field(description="Current snapshot ID")
    current_snapshot_created_at: datetime.datetime | None = Field(
        description="Current snapshot creation time"
    )
    latest_attempt: ModelCatalogSyncAttemptOutput | None = Field(
        description="Latest sync attempt"
    )
    stale: bool = Field(description="Whether the current projection is stale")
    sync_available_at: datetime.datetime | None = Field(
        description="Earliest time an explicit sync can start"
    )
    automatic_retry_blocked: bool = Field(
        description="Whether automatic stale retry is blocked by configuration failure"
    )
    entries: list[ModelCatalogEntryOutput] = Field(description="Entry page")
    total: int = Field(description="Total matching entries")
    limit: int = Field(description="Requested limit")
    offset: int = Field(description="Requested offset")


def _sync_policy_attempt(
    attempt: LLMCatalogSyncAttempt | None,
) -> CatalogSyncAttemptState | None:
    """Convert persisted attempt state into synchronization policy input."""
    if attempt is None:
        return None
    diagnostics = attempt.diagnostics or {}
    return CatalogSyncAttemptState(
        id=attempt.id,
        status=attempt.status,
        started_at=attempt.started_at,
        finished_at=attempt.finished_at,
        automatic_retry_blocked=(diagnostics.get("automatic_retry_blocked") is True),
    )


@dataclasses.dataclass(frozen=True)
class ModelCatalogReadService:
    """Read stored model catalog projections."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    catalog_repository: Annotated[LLMCatalogRepository, Depends(LLMCatalogRepository)]

    async def resolve_agent_model_selection(
        self,
        *,
        workspace_id: str,
        selection_input: AgentModelSelectionInput,
    ) -> Result[AgentModelSelection, CatalogNotFound]:
        """Resolve submitted selection through stored catalog projection."""
        async with self.session_manager() as session:
            result = await (
                self.catalog_repository.get_selectable_entry_by_integration_model
            )(
                session,
                integration_id=selection_input.llm_provider_integration_id,
                workspace_id=workspace_id,
                model_identifier=selection_input.model_identifier,
            )
        if result is None:
            return Failure(
                CatalogNotFound(
                    integration_id=selection_input.llm_provider_integration_id
                )
            )
        catalog, entry = result
        return Success(
            AgentModelSelection(
                llm_provider_integration_id=selection_input.llm_provider_integration_id,
                provider=entry.provider,
                model_identifier=entry.provider_model_identifier,
                model_display_name=entry.display_name,
                model_developer=_developer_from_entry(entry),
                model_family=entry.family,
                normalized_capabilities=ModelCapabilities.model_validate(
                    entry.normalized_capabilities
                ),
                model_snapshot={
                    "source": "stored_catalog_projection",
                    "catalog_id": catalog.id,
                    "snapshot_id": entry.snapshot_id,
                    "entry_id": entry.id,
                    "runtime_model_identifier": entry.runtime_model_identifier,
                    "lowerer_target": entry.lowerer_target.value,
                    "lifecycle_status": entry.lifecycle_status.value,
                },
                source_metadata=entry.source_metadata,
                last_refreshed_at=entry.created_at,
            )
        )

    async def list_entries_by_integration(
        self,
        *,
        integration_id: str,
        workspace_id: str,
        search: str | None,
        limit: int,
        offset: int,
    ) -> Result[ModelCatalogEntryListOutput, CatalogNotFound]:
        """List stored selectable entries for an integration catalog."""
        async with self.session_manager() as session:
            result = await self.catalog_repository.list_entries_by_integration(
                session,
                integration_id=integration_id,
                workspace_id=workspace_id,
                search=search,
                limit=limit,
                offset=offset,
            )
            if result is None:
                return Failure(CatalogNotFound(integration_id=integration_id))
            latest_workspace_attempt = None
            if result.catalog.scope == LLMCatalogScope.INTEGRATION:
                latest_workspace_attempt = await (
                    self.catalog_repository.get_latest_integration_attempt_for_workspace
                )(
                    session,
                    workspace_id=workspace_id,
                )
        policy = evaluate_integration_catalog_sync_policy(
            IntegrationCatalogSyncPolicyInput(
                trigger=IntegrationCatalogSyncTrigger.EXPLICIT,
                now=_utcnow(),
                current_snapshot_created_at=result.current_snapshot_created_at,
                latest_catalog_attempt=_sync_policy_attempt(result.latest_attempt),
                latest_workspace_attempt=_sync_policy_attempt(latest_workspace_attempt),
            )
        )
        automatic_retry_blocked = (
            result.latest_attempt is not None
            and (result.latest_attempt.diagnostics or {}).get("automatic_retry_blocked")
            is True
        )
        return Success(
            ModelCatalogEntryListOutput(
                catalog_id=result.catalog.id,
                catalog_scope=result.catalog.scope,
                current_snapshot_id=result.catalog.current_snapshot_id,
                current_snapshot_created_at=result.current_snapshot_created_at,
                latest_attempt=(
                    ModelCatalogSyncAttemptOutput.convert_from(result.latest_attempt)
                    if result.latest_attempt is not None
                    else None
                ),
                stale=policy.stale,
                sync_available_at=policy.retry_at,
                automatic_retry_blocked=automatic_retry_blocked,
                entries=[
                    ModelCatalogEntryOutput.convert_from(entry)
                    for entry in result.entries
                ],
                total=result.total,
                limit=limit,
                offset=offset,
            )
        )


@dataclasses.dataclass(frozen=True)
class LiteLLMSourceSyncService:
    """Synchronize LiteLLM model metadata into source snapshots."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    snapshot_repository: Annotated[
        LiteLLMSourceSnapshotRepository, Depends(LiteLLMSourceSnapshotRepository)
    ]

    async def sync_current_source(self) -> LiteLLMSourceSnapshot:
        """Store current LiteLLM model cost map as a source snapshot."""
        payload = current_litellm_model_cost_payload()
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        source_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        async with self.session_manager() as session:
            return await self.snapshot_repository.create_if_missing(
                session,
                source_key=_LITELLM_SOURCE_KEY,
                source_url=_LITELLM_SOURCE_URL,
                source_hash=source_hash,
                model_count=len(payload),
                litellm_version=getattr(litellm, "__version__", None),
                loaded_source="litellm_runtime",
                payload=payload,
            )


@dataclasses.dataclass(frozen=True)
class SystemCatalogProjectionService:
    """Project system catalogs from the latest LiteLLM source snapshot."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    catalog_repository: Annotated[LLMCatalogRepository, Depends(LLMCatalogRepository)]
    source_sync_service: Annotated[
        LiteLLMSourceSyncService, Depends(LiteLLMSourceSyncService)
    ]

    async def list_system_catalogs(self) -> list[SystemCatalogListItem]:
        """List supported system catalog states."""
        items: list[SystemCatalogListItem] = []
        async with self.session_manager() as session:
            for provider in _SYSTEM_PROVIDER_TO_LITELLM_PROVIDER:
                catalog = await self.catalog_repository.get_system_catalog(
                    session,
                    provider=provider,
                    lowerer_target=LLMCatalogLowererTarget.LITELLM,
                )
                if catalog is None:
                    items.append(
                        SystemCatalogListItem(
                            provider=provider,
                            catalog_id=None,
                            snapshot_id=None,
                            visible_count=0,
                            hidden_count=0,
                            latest_attempt=None,
                        )
                    )
                    continue
                counts = await self.catalog_repository.get_current_snapshot_counts(
                    session,
                    catalog=catalog,
                )
                latest_attempt = await self.catalog_repository.get_latest_attempt(
                    session,
                    catalog=catalog,
                )
                items.append(
                    SystemCatalogListItem(
                        provider=provider,
                        catalog_id=catalog.id,
                        snapshot_id=catalog.current_snapshot_id,
                        visible_count=counts.visible_count if counts else 0,
                        hidden_count=counts.hidden_count if counts else 0,
                        latest_attempt=(
                            ModelCatalogSyncAttemptOutput.convert_from(latest_attempt)
                            if latest_attempt is not None
                            else None
                        ),
                    )
                )
        return items

    async def sync_system_catalogs(self) -> list[SystemCatalogProjectionSummary]:
        """Refresh all system catalog projections from current LiteLLM metadata."""
        source_snapshot = await self.source_sync_service.sync_current_source()
        summaries: list[SystemCatalogProjectionSummary] = []
        for provider in _SYSTEM_PROVIDER_TO_LITELLM_PROVIDER:
            summaries.append(
                await self._sync_system_catalog(
                    provider=provider,
                    source_snapshot=source_snapshot,
                )
            )
        return summaries

    async def sync_system_catalog(
        self,
        *,
        provider: LLMProvider,
    ) -> SystemCatalogProjectionSummary:
        """Refresh one system catalog projection from current LiteLLM metadata."""
        if provider not in _SYSTEM_PROVIDER_TO_LITELLM_PROVIDER:
            raise ValueError("Unsupported system catalog provider.")
        source_snapshot = await self.source_sync_service.sync_current_source()
        return await self._sync_system_catalog(
            provider=provider,
            source_snapshot=source_snapshot,
        )

    async def _sync_system_catalog(
        self,
        *,
        provider: LLMProvider,
        source_snapshot: LiteLLMSourceSnapshot,
    ) -> SystemCatalogProjectionSummary:
        """Refresh one system catalog in a short transaction."""
        async with self.session_manager() as session:
            catalog = await self.catalog_repository.ensure_system_catalog(
                session,
                provider=provider,
                lowerer_target=LLMCatalogLowererTarget.LITELLM,
            )
            attempt = await self.catalog_repository.begin_attempt(
                session,
                catalog_id=catalog.id,
                source_key=source_snapshot.source_key,
                started_at=_utcnow(),
            )
            if isinstance(attempt, CatalogSyncAlreadyRunning):
                return SystemCatalogProjectionSummary(
                    provider=provider,
                    catalog_id=catalog.id,
                    snapshot_id=catalog.current_snapshot_id,
                    visible_count=0,
                    hidden_count=0,
                    status="running",
                )
            attempt_id = attempt
            try:
                entries = project_system_entries(
                    provider=provider,
                    source_snapshot=source_snapshot,
                )
                snapshot_id = await (self.catalog_repository.replace_current_snapshot)(
                    session,
                    catalog=catalog,
                    source_snapshot_id=source_snapshot.id,
                    entries=entries,
                    diagnostics=_projection_diagnostics(
                        entries=entries,
                        listing=None,
                        context={"source_key": source_snapshot.source_key},
                    ),
                )
                visible_count = sum(
                    entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
                    for entry in entries
                )
            except Exception as exc:
                await self.catalog_repository.mark_attempt_failed(
                    session,
                    attempt_id=attempt_id,
                    finished_at=_utcnow(),
                    failure_code=type(exc).__name__,
                    failure_message=str(exc),
                    action_hint="Check LiteLLM source payload and projection code.",
                    diagnostics={"provider": provider.value},
                )
                raise
            await self.catalog_repository.mark_attempt_succeeded(
                session,
                attempt_id=attempt_id,
                finished_at=_utcnow(),
                produced_snapshot_id=snapshot_id,
                fetched_count=source_snapshot.model_count,
                matched_count=len(entries),
                skipped_count=0,
                hidden_count=len(entries) - visible_count,
                diagnostics=_projection_diagnostics(
                    entries=entries,
                    listing=None,
                    context={"provider": provider.value},
                ),
            )
            return SystemCatalogProjectionSummary(
                provider=provider,
                catalog_id=catalog.id,
                snapshot_id=snapshot_id,
                visible_count=visible_count,
                hidden_count=len(entries) - visible_count,
            )


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogProjectionService:
    """Project integration catalogs from provider visibility and LiteLLM metadata."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    catalog_repository: Annotated[LLMCatalogRepository, Depends(LLMCatalogRepository)]
    integration_repository: Annotated[
        LLMProviderIntegrationRepository, Depends(_get_integration_repository)
    ]
    source_sync_service: Annotated[
        LiteLLMSourceSyncService, Depends(LiteLLMSourceSyncService)
    ]

    async def sync_integration_catalog(
        self,
        *,
        integration_id: str,
        workspace_id: str,
        trigger: IntegrationCatalogSyncTrigger = IntegrationCatalogSyncTrigger.EXPLICIT,
    ) -> Result[
        SystemCatalogProjectionSummary,
        IntegrationCatalogSyncNotFound
        | IntegrationCatalogSyncUnsupportedProvider
        | IntegrationCatalogSyncAlreadyRunning
        | IntegrationCatalogSyncSuperseded
        | IntegrationCatalogSyncThrottled
        | IntegrationCatalogAutomaticRetryBlocked
        | IntegrationCatalogSyncNotStale,
    ]:
        """Refresh one integration catalog projection."""
        async with self.session_manager() as session:
            integration = await self.integration_repository.get_by_id_with_secrets(
                session, integration_id
            )
        if integration is None or integration.workspace_id != workspace_id:
            return Failure(IntegrationCatalogSyncNotFound(integration_id))
        deterministic_failure = _deterministic_listing_failure(integration)
        deterministic_listing = (
            None if deterministic_failure else _deterministic_listing(integration)
        )
        if (
            deterministic_listing is None
            and not deterministic_failure
            and integration.provider not in INTEGRATION_SCOPED_CATALOG_PROVIDERS
        ):
            return Failure(
                IntegrationCatalogSyncUnsupportedProvider(integration.provider)
            )

        async with self.session_manager() as session:
            catalog = await self.catalog_repository.ensure_integration_catalog(
                session,
                integration_id=integration.id,
                provider=integration.provider,
                lowerer_target=LLMCatalogLowererTarget.LITELLM,
            )
        started_at = _utcnow()
        async with self.session_manager() as session:
            claim = await self.catalog_repository.begin_integration_attempt(
                session,
                catalog_id=catalog.id,
                workspace_id=workspace_id,
                source_key=_LITELLM_SOURCE_KEY,
                started_at=started_at,
                trigger=trigger,
            )
        if isinstance(claim, IntegrationCatalogSyncPolicyDecision):
            return Failure(_sync_policy_failure(catalog.id, claim))
        attempt_id = claim

        try:
            source_snapshot = await self.source_sync_service.sync_current_source()
            if deterministic_failure:
                raise ListingProviderError(
                    "Deterministic user catalog listing failed.",
                    automatic_retry_blocked=True,
                )
            if integration.provider == LLMProvider.CHATGPT_OAUTH:
                token_result = await ensure_runtime_tokens(
                    integration=integration,
                    integration_repository=self.integration_repository,
                    session_manager=self.session_manager,
                )
                match token_result:
                    case Success(refreshed_integration):
                        integration = refreshed_integration
                    case Failure(error):
                        match error:
                            case ProviderRejected(reason=reason):
                                raise ListingProviderError(
                                    reason,
                                    automatic_retry_blocked=True,
                                )
                            case ProviderUnavailable(reason=reason):
                                raise ListingProviderError(
                                    reason,
                                    automatic_retry_blocked=False,
                                )
                            case _:
                                assert_never(error)
            listing = deterministic_listing or await _list_provider_visible_models(
                integration
            )
            if deterministic_listing is not None:
                entries = project_deterministic_integration_entries(
                    integration_id=integration.id,
                    provider=integration.provider,
                    listing=deterministic_listing,
                    source_hash=source_snapshot.source_hash,
                )
            elif integration.provider == LLMProvider.CHATGPT_OAUTH:
                entries = project_chatgpt_integration_entries(
                    integration_id=integration.id,
                    listing=listing,
                    source_hash=source_snapshot.source_hash,
                )
            elif integration.provider == LLMProvider.OPENROUTER:
                entries = project_openrouter_integration_entries(
                    integration_id=integration.id,
                    listing=listing,
                    source_hash=source_snapshot.source_hash,
                )
            else:
                entries = project_integration_entries(
                    integration_id=integration.id,
                    provider=integration.provider,
                    listing=listing,
                    source_snapshot=source_snapshot,
                )
            async with self.session_manager() as session:
                current_attempt_id = await (
                    self.catalog_repository.lock_catalog_for_attempt_completion
                )(
                    session,
                    catalog_id=catalog.id,
                )
                if current_attempt_id is None:
                    raise RuntimeError(
                        "Integration catalog has no attempt allowed to publish."
                    )
                if current_attempt_id != attempt_id:
                    return Failure(
                        IntegrationCatalogSyncSuperseded(
                            catalog_id=catalog.id,
                            superseding_attempt_id=current_attempt_id,
                        )
                    )
                snapshot_id = await self.catalog_repository.replace_current_snapshot(
                    session,
                    catalog=catalog,
                    source_snapshot_id=source_snapshot.id,
                    entries=entries,
                    diagnostics=_projection_diagnostics(
                        entries=entries,
                        listing=listing,
                        context={
                            "integration_id": integration.id,
                            "source_key": source_snapshot.source_key,
                        },
                    ),
                )
                visible_count = sum(
                    entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
                    for entry in entries
                )
                await self.catalog_repository.mark_attempt_succeeded(
                    session,
                    attempt_id=attempt_id,
                    finished_at=_utcnow(),
                    produced_snapshot_id=snapshot_id,
                    fetched_count=listing.summary.returned_count,
                    matched_count=len(entries),
                    skipped_count=listing.summary.skipped_count,
                    hidden_count=len(entries) - visible_count,
                    diagnostics=_projection_diagnostics(
                        entries=entries,
                        listing=listing,
                        context={
                            "integration_id": integration.id,
                            "trigger": trigger.value,
                        },
                    ),
                )
        except ListingProviderError as exc:
            return Success(
                await self._record_listing_failure(
                    catalog_id=catalog.id,
                    snapshot_id=catalog.current_snapshot_id,
                    attempt_id=attempt_id,
                    integration=integration,
                    trigger=trigger,
                    error=exc,
                )
            )
        except Exception as exc:
            async with self.session_manager() as session:
                await self.catalog_repository.mark_attempt_failed(
                    session,
                    attempt_id=attempt_id,
                    finished_at=_utcnow(),
                    failure_code=type(exc).__name__,
                    failure_message=str(exc),
                    action_hint="Retry after the catalog service failure is resolved.",
                    diagnostics={
                        "integration_id": integration.id,
                        "failure_category": "catalog_service_failure",
                        "automatic_retry_blocked": False,
                        "trigger": trigger.value,
                    },
                )
            raise
        return Success(
            SystemCatalogProjectionSummary(
                provider=integration.provider,
                catalog_id=catalog.id,
                snapshot_id=snapshot_id,
                visible_count=visible_count,
                hidden_count=len(entries) - visible_count,
            )
        )

    async def _record_listing_failure(
        self,
        *,
        catalog_id: str,
        snapshot_id: str | None,
        attempt_id: str,
        integration: LLMProviderIntegrationWithSecrets,
        trigger: IntegrationCatalogSyncTrigger,
        error: ListingProviderError,
    ) -> SystemCatalogProjectionSummary:
        """Persist a provider failure and return its catalog state."""
        cause = error.__cause__
        failure_code = type(cause).__name__ if cause else type(error).__name__
        failure_message = str(cause or error)
        automatic_retry_blocked = error.automatic_retry_blocked
        action_hint = (
            "Check integration credentials and provider permissions."
            if automatic_retry_blocked
            else "Retry after the provider becomes available."
        )
        async with self.session_manager() as session:
            await self.catalog_repository.mark_attempt_failed(
                session,
                attempt_id=attempt_id,
                finished_at=_utcnow(),
                failure_code=failure_code,
                failure_message=failure_message,
                action_hint=action_hint,
                diagnostics={
                    "integration_id": integration.id,
                    "failure_category": (
                        "user_catalog_credentials_or_permissions"
                        if automatic_retry_blocked
                        else "provider_transient_failure"
                    ),
                    "automatic_retry_blocked": automatic_retry_blocked,
                    "retry_policy": (
                        "explicit_retry_or_integration_update_only"
                        if automatic_retry_blocked
                        else "throttled_backoff"
                    ),
                    "trigger": trigger.value,
                },
            )
        return SystemCatalogProjectionSummary(
            provider=integration.provider,
            catalog_id=catalog_id,
            snapshot_id=snapshot_id,
            visible_count=0,
            hidden_count=0,
            status="failed",
            failure_code=failure_code,
            failure_message=failure_message,
            action_hint=action_hint,
        )


def current_litellm_model_cost_payload() -> dict[str, Any]:
    """Return the current LiteLLM model cost map payload."""
    model_cost = getattr(litellm, "model_cost", None)
    if not isinstance(model_cost, dict):
        raise RuntimeError("LiteLLM model cost map is unavailable")
    return {str(key): value for key, value in model_cost.items()}


def _deterministic_listing_failure(
    integration: LLMProviderIntegrationWithSecrets,
) -> bool:
    """Return whether deterministic fixture should fail sync."""
    return (
        parse_deterministic_fixture_variant(integration.name) == "deterministic-failure"
    )


def _deterministic_listing(
    integration: LLMProviderIntegrationWithSecrets,
) -> ModelListingOutput | None:
    """Return deterministic listing when name is testenv fixture."""
    variant = parse_deterministic_fixture_variant(integration.name)
    if variant is None:
        return None
    return build_deterministic_listing(
        variant=variant,
        provider=integration.provider,
        integration_id=integration.id,
    )


async def _list_provider_visible_models(
    integration: LLMProviderIntegrationWithSecrets,
) -> ModelListingOutput:
    if integration.provider == LLMProvider.AWS_BEDROCK:
        return await list_bedrock_models_for_integration(integration)
    if integration.provider == LLMProvider.CHATGPT_OAUTH:
        return await list_chatgpt_models_for_integration(integration)
    if integration.provider == LLMProvider.OPENROUTER:
        return await list_openrouter_models_for_integration(integration)
    if integration.provider == LLMProvider.GOOGLE_VERTEX_AI:
        return await list_vertex_models_for_integration(integration)
    raise RuntimeError("Unsupported integration catalog provider")


def project_deterministic_integration_entries(
    *,
    integration_id: str,
    provider: LLMProvider,
    listing: ModelListingOutput,
    source_hash: str,
) -> list[LLMCatalogEntryCreate]:
    """Project deterministic testenv listing directly into integration catalog."""
    entries: list[LLMCatalogEntryCreate] = []
    for candidate in listing.models:
        entries.append(
            LLMCatalogEntryCreate(
                provider=provider,
                provider_model_identifier=candidate.model_identifier,
                lowerer_target=LLMCatalogLowererTarget.LITELLM,
                runtime_model_identifier=to_runtime_model(
                    provider,
                    candidate.model_identifier,
                ),
                display_name=candidate.model_display_name,
                normalized_capabilities=candidate.normalized_capabilities.model_dump(
                    mode="json"
                ),
                lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
                visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
                provider_integration_id=integration_id,
                publisher=candidate.model_developer.value,
                family=candidate.model_family,
                source_metadata={
                    "provider_listing_source": listing.summary.source,
                    "source_hash": source_hash,
                },
                projection_metadata={
                    "lowerer_target": LLMCatalogLowererTarget.LITELLM.value,
                    "testenv_fixture": True,
                    "freshness_rank": model_freshness_rank(candidate.model_identifier),
                },
                hidden_reason=None,
            )
        )
    return entries


def project_chatgpt_integration_entries(
    *,
    integration_id: str,
    listing: ModelListingOutput,
    source_hash: str,
) -> list[LLMCatalogEntryCreate]:
    """Project ChatGPT backend models without requiring LiteLLM metadata."""
    entries: list[LLMCatalogEntryCreate] = []
    for candidate in listing.models:
        capabilities = candidate.normalized_capabilities
        entries.append(
            LLMCatalogEntryCreate(
                provider=LLMProvider.CHATGPT_OAUTH,
                provider_model_identifier=candidate.model_identifier,
                lowerer_target=LLMCatalogLowererTarget.LITELLM,
                runtime_model_identifier=candidate.model_identifier,
                display_name=candidate.model_display_name,
                normalized_capabilities=capabilities.model_dump(mode="json"),
                lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
                visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
                provider_integration_id=integration_id,
                publisher=candidate.model_developer.value,
                family=candidate.model_family,
                source_metadata={
                    "provider_listing_source": listing.summary.source,
                    "provider_metadata": candidate.source_metadata,
                    "source_hash": source_hash,
                },
                projection_metadata={
                    "lowerer_target": LLMCatalogLowererTarget.LITELLM.value,
                    "freshness_rank": model_freshness_rank(candidate.model_identifier),
                },
                hidden_reason=None,
            )
        )
    return entries


def project_openrouter_integration_entries(
    *,
    integration_id: str,
    listing: ModelListingOutput,
    source_hash: str,
) -> list[LLMCatalogEntryCreate]:
    """Project OpenRouter account models without LiteLLM visibility matching."""
    entries: list[LLMCatalogEntryCreate] = []
    for candidate in listing.models:
        entries.append(
            LLMCatalogEntryCreate(
                provider=LLMProvider.OPENROUTER,
                provider_model_identifier=candidate.model_identifier,
                lowerer_target=LLMCatalogLowererTarget.LITELLM,
                runtime_model_identifier=to_runtime_model(
                    LLMProvider.OPENROUTER,
                    candidate.model_identifier,
                ),
                display_name=candidate.model_display_name,
                normalized_capabilities=candidate.normalized_capabilities.model_dump(
                    mode="json"
                ),
                lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
                visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
                provider_integration_id=integration_id,
                publisher=candidate.model_developer.value,
                family=candidate.model_family,
                source_metadata={
                    "provider_listing_source": listing.summary.source,
                    "provider_metadata": candidate.source_metadata,
                    "source_hash": source_hash,
                },
                projection_metadata={
                    "lowerer_target": LLMCatalogLowererTarget.LITELLM.value,
                    "target_metadata_match_required": False,
                    "freshness_rank": model_freshness_rank(candidate.model_identifier),
                },
                hidden_reason=None,
            )
        )
    return entries


def project_integration_entries(
    *,
    integration_id: str,
    provider: LLMProvider,
    listing: ModelListingOutput,
    source_snapshot: LiteLLMSourceSnapshot,
) -> list[LLMCatalogEntryCreate]:
    """Project provider-visible integration models against LiteLLM metadata."""
    entries: list[LLMCatalogEntryCreate] = []
    for candidate in listing.models:
        source_key = _integration_projection_key(provider, candidate.model_identifier)
        metadata = source_snapshot.payload.get(source_key)
        hidden_reason = (
            None if isinstance(metadata, dict) else "missing_target_projection"
        )
        if not isinstance(metadata, dict):
            metadata = {}
        visibility = (
            LLMCatalogEntryVisibility.HIDDEN
            if hidden_reason is not None
            else LLMCatalogEntryVisibility.SELECTABLE
        )
        capabilities = (
            _capabilities_from_litellm_metadata(
                metadata,
                provider=provider,
                model_identifier=candidate.model_identifier,
            )
            if hidden_reason is None
            else candidate.normalized_capabilities
        )
        entries.append(
            LLMCatalogEntryCreate(
                provider=provider,
                provider_model_identifier=candidate.model_identifier,
                lowerer_target=LLMCatalogLowererTarget.LITELLM,
                runtime_model_identifier=source_key,
                display_name=candidate.model_display_name,
                normalized_capabilities=capabilities.model_dump(mode="json"),
                lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
                visibility_status=visibility,
                provider_integration_id=integration_id,
                publisher=candidate.model_developer.value,
                family=candidate.model_family,
                source_metadata={
                    "provider_listing_source": listing.summary.source,
                    "target_projection_key": source_key,
                    "source_hash": source_snapshot.source_hash,
                },
                projection_metadata={
                    "lowerer_target": LLMCatalogLowererTarget.LITELLM.value,
                    "matched": hidden_reason is None,
                    "freshness_rank": model_freshness_rank(candidate.model_identifier),
                    "exact_projection_key": source_key,
                },
                hidden_reason=hidden_reason,
            )
        )
    return entries


def _integration_projection_key(provider: LLMProvider, model_identifier: str) -> str:
    if provider == LLMProvider.AWS_BEDROCK:
        return f"bedrock/{model_identifier}"
    if provider == LLMProvider.GOOGLE_VERTEX_AI:
        return f"vertex_ai/{model_identifier}"
    raise RuntimeError("Unsupported integration catalog provider")


def project_system_entries(
    *,
    provider: LLMProvider,
    source_snapshot: LiteLLMSourceSnapshot,
) -> list[LLMCatalogEntryCreate]:
    litellm_providers = _SYSTEM_PROVIDER_TO_LITELLM_PROVIDER[provider]
    entries: list[LLMCatalogEntryCreate] = []
    for model_key, metadata in source_snapshot.payload.items():
        if not isinstance(metadata, dict):
            continue
        if metadata.get("litellm_provider") not in litellm_providers:
            continue
        hidden_reason = _hidden_reason(model_key, metadata)
        visibility = (
            LLMCatalogEntryVisibility.HIDDEN
            if hidden_reason is not None
            else LLMCatalogEntryVisibility.SELECTABLE
        )
        entries.append(
            LLMCatalogEntryCreate(
                provider=provider,
                provider_model_identifier=_provider_model_identifier(
                    provider, model_key
                ),
                lowerer_target=LLMCatalogLowererTarget.LITELLM,
                runtime_model_identifier=model_key,
                display_name=_display_name(model_key),
                normalized_capabilities=_capabilities_from_litellm_metadata(
                    metadata,
                    provider=provider,
                    model_identifier=_provider_model_identifier(provider, model_key),
                ).model_dump(mode="json"),
                lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
                visibility_status=visibility,
                provider_integration_id=None,
                publisher=metadata.get("litellm_provider"),
                family=_family(model_key),
                source_metadata={
                    "model_key": model_key,
                    "source_hash": source_snapshot.source_hash,
                },
                projection_metadata={
                    "lowerer_target": LLMCatalogLowererTarget.LITELLM.value,
                    "litellm_provider": metadata.get("litellm_provider"),
                    "freshness_rank": model_freshness_rank(
                        _provider_model_identifier(provider, model_key)
                    ),
                },
                hidden_reason=hidden_reason,
            )
        )
    return entries


def _hidden_reason(model_key: str, metadata: dict[str, Any]) -> str | None:
    mode = metadata.get("mode")
    if mode not in (None, "chat", "completion"):
        return f"unsupported_mode:{mode}"
    if model_key == "sample_spec":
        return "sample_spec"
    if model_key.startswith("ft:"):
        return "fine_tuned_model"
    return None


def _provider_model_identifier(provider: LLMProvider, model_key: str) -> str:
    if provider == LLMProvider.GOOGLE_GEMINI and model_key.startswith("gemini/"):
        return model_key.removeprefix("gemini/")
    if provider in {LLMProvider.XAI, LLMProvider.XAI_OAUTH} and model_key.startswith(
        "xai/"
    ):
        return model_key.removeprefix("xai/")
    return model_key.removeprefix("openai/").removeprefix("anthropic/")


def _display_name(model_key: str) -> str:
    return model_key.rsplit("/", maxsplit=1)[-1]


def _family(model_key: str) -> str | None:
    name = _display_name(model_key)
    if not name:
        return None
    return name.split("-", maxsplit=1)[0]


def model_freshness_rank(model_identifier: str) -> int:
    """Rank model identifiers so newer generations sort first."""
    match = re.search(r"(\d+)(?:\.(\d+))?", model_identifier)
    if match is None:
        return 0
    major = int(match.group(1))
    minor = int(match.group(2) or "0")
    preview_bonus = 1 if "preview" in model_identifier.lower() else 0
    return major * 1000 + minor * 10 + preview_bonus


def _projection_diagnostics(
    *,
    entries: list[LLMCatalogEntryCreate],
    listing: ModelListingOutput | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Build projection diagnostics for catalog sync attempts."""
    hidden_reasons: dict[str, int] = {}
    exact_match_misses: list[str] = []
    for entry in entries:
        if entry.hidden_reason is None:
            continue
        hidden_reasons[entry.hidden_reason] = (
            hidden_reasons.get(entry.hidden_reason, 0) + 1
        )
        if entry.hidden_reason == "missing_target_projection":
            exact_match_misses.append(entry.provider_model_identifier)
    return {
        **context,
        "candidate_count": (
            listing.summary.returned_count if listing is not None else len(entries)
        ),
        "projected_count": len(entries),
        "visible_count": sum(
            entry.visibility_status == LLMCatalogEntryVisibility.SELECTABLE
            for entry in entries
        ),
        "hidden_count": sum(
            entry.visibility_status == LLMCatalogEntryVisibility.HIDDEN
            for entry in entries
        ),
        "hidden_reasons": hidden_reasons,
        "exact_match_misses": exact_match_misses[:50],
    }


def _capabilities_from_litellm_metadata(
    metadata: dict[str, Any],
    *,
    provider: LLMProvider,
    model_identifier: str,
) -> ModelCapabilities:
    provider_info = _PROVIDER_MODEL_INFO_ADAPTER.validate_python(metadata)
    return ModelCapabilities(
        context_window=ModelContextWindow(
            max_input_tokens=_positive_int(metadata.get("max_input_tokens")),
            max_output_tokens=_positive_int(metadata.get("max_output_tokens")),
        ),
        modalities=ModelModalities(
            input=_modalities_from_metadata(metadata),
            output=[ModelModality.TEXT],
        ),
        tool_calling=ModelToolCallingCapabilities(
            supported=metadata.get("supports_function_calling") is True,
            parallel_tool_calls=metadata.get("supports_parallel_function_calling"),
            strict_json_schema=metadata.get("supports_response_schema"),
        ),
        reasoning=ModelReasoningCapabilities(
            supported=provider_info.get("supports_reasoning") is True,
            effort_levels=_reasoning_effort_levels(provider_info),
        ),
        built_in_tools=ModelBuiltInToolCapabilities(
            supported=supported_builtin_capabilities(
                provider=provider,
                model_identifier=model_identifier,
                metadata=metadata,
            )
        ),
        compatibility=ModelCompatibilityCapabilities(
            provider_family=_str_or_none(metadata.get("litellm_provider")),
            responses_api=True,
        ),
    )


def _reasoning_effort_levels(
    model_info: ProviderSpecificModelInfo,
) -> list[ModelReasoningEffort]:
    """Reconstruct ordered explicit efforts from LiteLLM capability flags."""
    if model_info.get("supports_reasoning") is not True:
        return []

    efforts: list[ModelReasoningEffort] = []
    if model_info.get("supports_none_reasoning_effort") is True:
        efforts.append(ModelReasoningEffort.NONE)
    if model_info.get("supports_minimal_reasoning_effort") is True:
        efforts.append(ModelReasoningEffort.MINIMAL)

    if model_info.get("supports_low_reasoning_effort") is not False:
        efforts.append(ModelReasoningEffort.LOW)
    efforts.extend((ModelReasoningEffort.MEDIUM, ModelReasoningEffort.HIGH))

    if model_info.get("supports_xhigh_reasoning_effort") is True:
        efforts.append(ModelReasoningEffort.XHIGH)
    if model_info.get("supports_max_reasoning_effort") is True:
        efforts.append(ModelReasoningEffort.MAX)
    return efforts


def _modalities_from_metadata(metadata: dict[str, Any]) -> list[ModelModality]:
    result = [ModelModality.TEXT]
    if metadata.get("supports_vision") is True:
        result.append(ModelModality.IMAGE)
    if metadata.get("supports_pdf_input") is True:
        result.append(ModelModality.PDF)
    if metadata.get("supports_audio_input") is True:
        result.append(ModelModality.AUDIO)
    if metadata.get("supports_video_input") is True:
        result.append(ModelModality.VIDEO)
    return result


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _str_or_none(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)
