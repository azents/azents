"""LLM catalog sync services."""

import dataclasses
import datetime
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from pydantic import BaseModel, Field

from azents.core.agent import AgentModelSelection, AgentModelSelectionInput
from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMCatalogScope,
    LLMModelDeveloper,
    LLMModelLifecycleStatus,
    LLMProvider,
)
from azents.core.llm_catalog import (
    INTEGRATION_SCOPED_CATALOG_PROVIDERS,
    ModelCapabilities,
    model_freshness_rank,
)
from azents.core.llm_catalog_sync import (
    CatalogProjectionVersion,
    CatalogSyncAttemptState,
    IntegrationCatalogSyncDenialReason,
    IntegrationCatalogSyncPolicyDecision,
    IntegrationCatalogSyncPolicyInput,
    IntegrationCatalogSyncTrigger,
    evaluate_integration_catalog_sync_policy,
)
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.engine.providers.model_profiles import (
    RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
)
from azents.repos.chatgpt_oauth_runtime import ChatGPTOAuthRuntimeRepository
from azents.repos.kimi_oauth_runtime import KimiOAuthRuntimeRepository
from azents.repos.llm_catalog.data import (
    CatalogNotFound,
    CatalogProjectionProvenance,
    CatalogRetryPolicy,
    LLMCatalogEntry,
    LLMCatalogEntryCreate,
    LLMCatalogSyncAttempt,
)
from azents.repos.llm_catalog_operations import (
    CatalogAttemptFailure,
    CatalogPublicationSuperseded,
    LLMCatalogOperationsRepository,
)
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot
from azents.repos.xai_oauth_runtime import XaiOAuthRuntimeRepository
from azents.services.chatgpt_oauth.data import ProviderRejected, ProviderUnavailable
from azents.services.chatgpt_oauth.runtime import ensure_runtime_tokens
from azents.services.kimi_oauth.data import ProviderRejected as KimiProviderRejected
from azents.services.kimi_oauth.data import (
    ProviderUnavailable as KimiProviderUnavailable,
)
from azents.services.kimi_oauth.runtime import (
    ensure_runtime_tokens as ensure_kimi_runtime_tokens,
)
from azents.services.model_listing.data import ModelListingOutput
from azents.services.model_listing.providers import (
    ListingClientFactories,
    ListingProviderError,
    XaiListingProviderError,
    create_listing_client_factories,
    list_bedrock_models_for_integration,
    list_chatgpt_models_for_integration,
    list_kimi_models_for_integration,
    list_openrouter_models_for_integration,
    list_vertex_models_for_integration,
    list_xai_models_for_integration,
)
from azents.services.model_metadata_projection import (
    MODEL_METADATA_PROJECTION_SCHEMA_VERSION,
    SystemCatalogReplacementProjectionService,
    integration_projection_fingerprint,
    project_integration_replacement_entries,
    projection_runtime_versions,
)
from azents.services.model_metadata_source import (
    ModelMetadataSourceSyncService,
)
from azents.services.oauth_runtime_clients import (
    RuntimeOAuthClientFactories,
    create_runtime_oauth_client_factories,
)
from azents.services.xai_oauth.data import (
    ProviderEntitlementDenied as XaiProviderEntitlementDenied,
)
from azents.services.xai_oauth.data import ProviderRejected as XaiProviderRejected
from azents.services.xai_oauth.data import (
    ProviderUnavailable as XaiProviderUnavailable,
)
from azents.services.xai_oauth.runtime import (
    ensure_runtime_tokens as ensure_xai_runtime_tokens,
)
from azents.testing.deterministic_model_listing import (
    build_deterministic_listing,
    parse_deterministic_fixture_variant,
)

_SYSTEM_CATALOG_PROVIDERS = (
    LLMProvider.OPENAI,
    LLMProvider.ANTHROPIC,
    LLMProvider.GOOGLE_GEMINI,
)
_PROVIDER_TO_DEVELOPER: dict[LLMProvider, LLMModelDeveloper] = {
    LLMProvider.OPENAI: LLMModelDeveloper.OPENAI,
    LLMProvider.CHATGPT_OAUTH: LLMModelDeveloper.OPENAI,
    LLMProvider.XAI: LLMModelDeveloper.XAI,
    LLMProvider.XAI_OAUTH: LLMModelDeveloper.XAI,
    LLMProvider.KIMI_OAUTH: LLMModelDeveloper.MOONSHOT,
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
    display_name: str = Field(description="Display name")
    normalized_capabilities: ModelCapabilities = Field(
        description="Normalized capability contract"
    )
    supported_execution_options: list[ModelExecutionOptionId] = Field(
        description="Directly selectable execution options supported by this model"
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
            display_name=entry.display_name,
            normalized_capabilities=ModelCapabilities.model_validate(
                entry.normalized_capabilities
            ),
            supported_execution_options=[
                ModelExecutionOptionId(option)
                for option in entry.supported_execution_options
            ],
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
    retry_policy = CatalogRetryPolicy.from_diagnostics(attempt.diagnostics)
    return CatalogSyncAttemptState(
        id=attempt.id,
        status=attempt.status,
        started_at=attempt.started_at,
        finished_at=attempt.finished_at,
        automatic_retry_blocked=retry_policy.automatic_retry_blocked,
    )


@dataclasses.dataclass(frozen=True)
class ModelCatalogReadService:
    """Read stored model catalog projections."""

    operations: Annotated[
        LLMCatalogOperationsRepository, Depends(LLMCatalogOperationsRepository)
    ]

    async def resolve_agent_model_selection(
        self,
        *,
        workspace_id: str,
        selection_input: AgentModelSelectionInput,
    ) -> Result[AgentModelSelection, CatalogNotFound]:
        """Resolve submitted selection through stored catalog projection."""
        result = await self.operations.selectable_entry(
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
        catalog = result.catalog
        entry = result.entry
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
                supported_execution_options=[
                    ModelExecutionOptionId(option)
                    for option in entry.supported_execution_options
                ],
                model_snapshot={
                    "source": "stored_catalog_projection",
                    "catalog_id": catalog.id,
                    "snapshot_id": entry.snapshot_id,
                    "entry_id": entry.id,
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
        snapshot = await self.operations.read_page(
            integration_id=integration_id,
            workspace_id=workspace_id,
            search=search,
            limit=limit,
            offset=offset,
        )
        if snapshot is None:
            return Failure(CatalogNotFound(integration_id=integration_id))
        result = snapshot.page
        latest_workspace_attempt = snapshot.latest_workspace_attempt
        policy = evaluate_integration_catalog_sync_policy(
            IntegrationCatalogSyncPolicyInput(
                trigger=IntegrationCatalogSyncTrigger.EXPLICIT,
                now=_utcnow(),
                current_snapshot_created_at=result.current_snapshot_created_at,
                current_projection_version=snapshot.current_projection_version,
                required_projection_version=CatalogProjectionVersion(
                    schema_version=MODEL_METADATA_PROJECTION_SCHEMA_VERSION,
                    resolver_revision=RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
                ),
                latest_catalog_attempt=_sync_policy_attempt(result.latest_attempt),
                latest_workspace_attempt=_sync_policy_attempt(latest_workspace_attempt),
            )
        )
        automatic_retry_blocked = CatalogRetryPolicy.from_diagnostics(
            result.latest_attempt.diagnostics
            if result.latest_attempt is not None
            else None
        ).automatic_retry_blocked
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
class SystemCatalogProjectionService:
    """Publish replacement system catalogs from generic metadata authority."""

    operations: Annotated[
        LLMCatalogOperationsRepository, Depends(LLMCatalogOperationsRepository)
    ]
    replacement_projection_service: Annotated[
        SystemCatalogReplacementProjectionService,
        Depends(SystemCatalogReplacementProjectionService),
    ]

    async def list_system_catalogs(self) -> list[SystemCatalogListItem]:
        """List supported system catalog states."""
        items: list[SystemCatalogListItem] = []
        snapshots = await self.operations.read_system_catalogs(
            _SYSTEM_CATALOG_PROVIDERS
        )
        for snapshot in snapshots:
            catalog = snapshot.catalog
            counts = snapshot.counts
            latest_attempt = snapshot.latest_attempt
            if catalog is None:
                items.append(
                    SystemCatalogListItem(
                        provider=snapshot.provider,
                        catalog_id=None,
                        snapshot_id=None,
                        visible_count=0,
                        hidden_count=0,
                        latest_attempt=None,
                    )
                )
                continue
            items.append(
                SystemCatalogListItem(
                    provider=snapshot.provider,
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
        """Refresh and publish all replacement system catalog projections."""
        summaries = (
            await self.replacement_projection_service.prepare_and_publish_cutover(
                provider=None
            )
        )
        return [
            SystemCatalogProjectionSummary(
                provider=summary.provider,
                catalog_id=summary.catalog_id,
                snapshot_id=summary.snapshot_id,
                visible_count=summary.visible_count,
                hidden_count=summary.hidden_count,
                status=summary.status,
            )
            for summary in summaries
        ]

    async def sync_system_catalog(
        self,
        *,
        provider: LLMProvider,
    ) -> SystemCatalogProjectionSummary:
        """Refresh and publish one replacement system catalog projection."""
        if provider not in _SYSTEM_CATALOG_PROVIDERS:
            raise ValueError("Unsupported system catalog provider.")
        summaries = (
            await self.replacement_projection_service.prepare_and_publish_cutover(
                provider=provider
            )
        )
        summary = summaries[0]
        return SystemCatalogProjectionSummary(
            provider=summary.provider,
            catalog_id=summary.catalog_id,
            snapshot_id=summary.snapshot_id,
            visible_count=summary.visible_count,
            hidden_count=summary.hidden_count,
            status=summary.status,
        )


type IntegrationModelListing = Callable[
    [LLMProviderIntegrationWithSecrets, ListingClientFactories],
    Awaitable[ModelListingOutput],
]


async def provider_model_listing(
    integration: LLMProviderIntegrationWithSecrets,
    clients: ListingClientFactories,
) -> ModelListingOutput:
    """Dispatch the existing provider-owned discovery operation."""
    return await _list_provider_visible_models(integration, clients=clients)


def get_integration_model_listing() -> IntegrationModelListing:
    """Provide the normal discovery collaborator at process composition."""
    return provider_model_listing


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogProjectionService:
    """Project integration catalogs from provider visibility and generic metadata."""

    operations: Annotated[
        LLMCatalogOperationsRepository, Depends(LLMCatalogOperationsRepository)
    ]
    kimi_oauth_runtime_repository: Annotated[
        KimiOAuthRuntimeRepository, Depends(KimiOAuthRuntimeRepository)
    ]
    chatgpt_oauth_runtime_repository: Annotated[
        ChatGPTOAuthRuntimeRepository, Depends(ChatGPTOAuthRuntimeRepository)
    ]
    xai_oauth_runtime_repository: Annotated[
        XaiOAuthRuntimeRepository, Depends(XaiOAuthRuntimeRepository)
    ]
    listing_clients: Annotated[
        ListingClientFactories, Depends(create_listing_client_factories)
    ]
    oauth_clients: Annotated[
        RuntimeOAuthClientFactories, Depends(create_runtime_oauth_client_factories)
    ]
    source_sync_service: Annotated[
        ModelMetadataSourceSyncService, Depends(ModelMetadataSourceSyncService)
    ]
    provider_listing: Annotated[
        IntegrationModelListing, Depends(get_integration_model_listing)
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
        integration = await self.operations.load_integration(integration_id)
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

        started_at = _utcnow()
        preparation = await self.operations.begin_attempt(
            integration_id=integration.id,
            provider=integration.provider,
            workspace_id=workspace_id,
            started_at=started_at,
            trigger=trigger,
            required_projection_version=CatalogProjectionVersion(
                schema_version=MODEL_METADATA_PROJECTION_SCHEMA_VERSION,
                resolver_revision=RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
            ),
        )
        catalog = preparation.catalog
        claim = preparation.claim
        if isinstance(claim, IntegrationCatalogSyncPolicyDecision):
            return Failure(_sync_policy_failure(catalog.id, claim))
        attempt_id = claim.attempt_id

        try:
            refreshed_integration = await self.operations.load_integration(
                integration_id
            )
            if (
                refreshed_integration is None
                or refreshed_integration.workspace_id != workspace_id
            ):
                raise ListingProviderError(
                    "The integration disappeared after synchronization started.",
                    automatic_retry_blocked=True,
                )
            if (
                refreshed_integration.catalog_configuration_version
                != claim.catalog_configuration_version
            ):
                raise ListingProviderError(
                    "The integration configuration changed after synchronization "
                    "started.",
                    automatic_retry_blocked=False,
                )
            integration = refreshed_integration
            source_snapshot: (
                ModelMetadataSourceSnapshot | None
            ) = await self.source_sync_service.get_current_source()
            if deterministic_failure:
                raise ListingProviderError(
                    "Deterministic user catalog listing failed.",
                    automatic_retry_blocked=True,
                )
            if integration.provider == LLMProvider.CHATGPT_OAUTH:
                token_result = await ensure_runtime_tokens(
                    integration=integration,
                    persistence_repository=self.chatgpt_oauth_runtime_repository,
                    client_factory=self.oauth_clients.chatgpt,
                )
                if token_result.success:
                    refreshed_integration = token_result.value
                    integration = refreshed_integration
                else:
                    error = token_result.error
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
            elif integration.provider == LLMProvider.KIMI_OAUTH:
                kimi_token_result = await ensure_kimi_runtime_tokens(
                    integration=integration,
                    persistence_repository=self.kimi_oauth_runtime_repository,
                    client_factory=self.oauth_clients.kimi,
                )
                if kimi_token_result.success:
                    refreshed_integration = kimi_token_result.value
                    integration = refreshed_integration
                else:
                    error = kimi_token_result.error
                    match error:
                        case KimiProviderRejected(reason=reason):
                            raise ListingProviderError(
                                reason,
                                automatic_retry_blocked=True,
                            )
                        case KimiProviderUnavailable(reason=reason):
                            raise ListingProviderError(
                                reason,
                                automatic_retry_blocked=False,
                            )
                        case _:
                            assert_never(error)
            elif integration.provider == LLMProvider.XAI_OAUTH:
                xai_token_result = await ensure_xai_runtime_tokens(
                    integration=integration,
                    persistence_repository=self.xai_oauth_runtime_repository,
                    client_factory=self.oauth_clients.xai,
                )
                if xai_token_result.success:
                    integration = xai_token_result.value
                else:
                    error = xai_token_result.error
                    match error:
                        case (
                            XaiProviderRejected(reason=reason)
                            | XaiProviderEntitlementDenied(reason=reason)
                        ):
                            raise ListingProviderError(
                                reason,
                                automatic_retry_blocked=True,
                            )
                        case XaiProviderUnavailable(reason=reason):
                            raise ListingProviderError(
                                reason,
                                automatic_retry_blocked=False,
                            )
                        case _:
                            assert_never(error)
            listing = deterministic_listing or await self.provider_listing(
                integration, self.listing_clients
            )
            if deterministic_listing is not None:
                entries = project_deterministic_integration_entries(
                    integration_id=integration.id,
                    provider=integration.provider,
                    listing=deterministic_listing,
                )
            else:
                entries = project_integration_replacement_entries(
                    integration_id=integration.id,
                    provider=integration.provider,
                    candidates=listing.models,
                    source=source_snapshot,
                    provider_listing_source=listing.summary.source,
                )
            fingerprint = integration_projection_fingerprint(
                provider=integration.provider,
                source=source_snapshot,
                entries=entries,
                catalog_configuration_version=claim.catalog_configuration_version,
            )
            provenance = CatalogProjectionProvenance(
                source_snapshot_id=(
                    source_snapshot.id if source_snapshot is not None else None
                ),
                projection_schema_version=(MODEL_METADATA_PROJECTION_SCHEMA_VERSION),
                runtime_profile_resolver_revision=(
                    RUNTIME_MODEL_PROFILE_RESOLVER_REVISION
                ),
                pydantic_ai_version=projection_runtime_versions(
                    integration.provider
                ).get("pydantic-ai-slim"),
                genai_prices_version=None,
                projection_fingerprint=fingerprint,
            )
            publication = await self.operations.publish(
                catalog=catalog,
                claim=claim,
                entries=entries,
                provenance=provenance,
                candidate_diagnostics=_projection_diagnostics(
                    entries=entries,
                    listing=listing,
                    context={
                        "integration_id": integration.id,
                        "source_key": (
                            source_snapshot.source_key
                            if source_snapshot is not None
                            else None
                        ),
                        "projection_fingerprint": fingerprint,
                    },
                ),
                attempt_diagnostics=_projection_diagnostics(
                    entries=entries,
                    listing=listing,
                    context={
                        "integration_id": integration.id,
                        "trigger": trigger.value,
                    },
                ),
                fetched_count=listing.summary.returned_count,
                skipped_count=listing.summary.skipped_count,
                finished_at=_utcnow(),
            )
            if isinstance(publication, CatalogPublicationSuperseded):
                return Failure(
                    IntegrationCatalogSyncSuperseded(
                        catalog_id=catalog.id,
                        superseding_attempt_id=publication.superseding_attempt_id,
                    )
                )
            snapshot_id = publication.snapshot_id
            visible_count = publication.visible_count
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
            await self.operations.fail_attempt(
                CatalogAttemptFailure(
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
        if isinstance(error, XaiListingProviderError):
            failure_code = error.failure_code
            failure_message = str(error)
        else:
            failure_code = type(cause).__name__ if cause else type(error).__name__
            failure_message = str(cause or error)
        automatic_retry_blocked = error.automatic_retry_blocked
        action_hint = (
            "Check integration credentials and provider permissions."
            if automatic_retry_blocked
            else "Retry after the provider becomes available."
        )
        await self.operations.fail_attempt(
            CatalogAttemptFailure(
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
    *,
    clients: ListingClientFactories,
) -> ModelListingOutput:
    if integration.provider == LLMProvider.AWS_BEDROCK:
        return await list_bedrock_models_for_integration(integration, clients=clients)
    if integration.provider == LLMProvider.CHATGPT_OAUTH:
        return await list_chatgpt_models_for_integration(integration, clients=clients)
    if integration.provider == LLMProvider.KIMI_OAUTH:
        return await list_kimi_models_for_integration(integration, clients=clients)
    if integration.provider == LLMProvider.OPENROUTER:
        return await list_openrouter_models_for_integration(
            integration, clients=clients
        )
    if integration.provider in {LLMProvider.XAI, LLMProvider.XAI_OAUTH}:
        return await list_xai_models_for_integration(integration, clients=clients)
    if integration.provider == LLMProvider.GOOGLE_VERTEX_AI:
        return await list_vertex_models_for_integration(integration, clients=clients)
    raise RuntimeError("Unsupported integration catalog provider")


def project_deterministic_integration_entries(
    *,
    integration_id: str,
    provider: LLMProvider,
    listing: ModelListingOutput,
) -> list[LLMCatalogEntryCreate]:
    """Project deterministic testenv listing directly into integration catalog."""
    entries: list[LLMCatalogEntryCreate] = []
    for candidate in listing.models:
        entries.append(
            LLMCatalogEntryCreate(
                provider=provider,
                provider_model_identifier=candidate.model_identifier,
                display_name=candidate.model_display_name,
                normalized_capabilities=candidate.normalized_capabilities.model_dump(
                    mode="json"
                ),
                supported_execution_options=[
                    option.value for option in candidate.supported_execution_options
                ],
                lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
                visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
                provider_integration_id=integration_id,
                publisher=candidate.model_developer.value,
                family=candidate.model_family,
                source_metadata={
                    "provider_listing_source": listing.summary.source,
                },
                projection_metadata={
                    "testenv_fixture": True,
                    "freshness_rank": model_freshness_rank(candidate.model_identifier),
                },
                hidden_reason=None,
            )
        )
    return entries


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
            if (
                entry.provider in {LLMProvider.XAI, LLMProvider.XAI_OAUTH}
                and (entry.projection_metadata or {}).get("matched") is False
            ):
                exact_match_misses.append(entry.provider_model_identifier)
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


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)
