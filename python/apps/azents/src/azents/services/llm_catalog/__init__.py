"""Current model catalog reads and credential-fenced synchronization."""

import asyncio
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
    CatalogSyncState,
    IntegrationCatalogSyncDenialReason,
    IntegrationCatalogSyncPolicyDecision,
    IntegrationCatalogSyncPolicyInput,
    IntegrationCatalogSyncTrigger,
    evaluate_integration_catalog_sync_policy,
)
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.core.model_pricing import ModelPricingDefinition
from azents.repos.chatgpt_oauth_runtime import ChatGPTOAuthRuntimeRepository
from azents.repos.kimi_oauth_runtime import KimiOAuthRuntimeRepository
from azents.repos.llm_catalog.data import (
    CatalogNotFound,
    CatalogRetryPolicy,
    LLMCatalog,
    LLMCatalogEntry,
    LLMCatalogEntryCreate,
    LLMCatalogSyncStatus,
)
from azents.repos.llm_catalog_operations import (
    CatalogPublicationSourceChanged,
    CatalogPublicationSuperseded,
    CatalogSyncFailure,
    LLMCatalogOperationsRepository,
)
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.repos.model_metadata_source_data import (
    ModelMetadataSource,
    SourceProjectionMetadata,
)
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
    project_integration_replacement_entries,
    projection_source_expectations,
)
from azents.services.model_metadata_source import (
    ModelMetadataSourceSyncBusy,
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
from azents.services.xai_oauth.data import ProviderUnavailable as XaiProviderUnavailable
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
_PROVIDER_TO_DEVELOPER = {
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
    for candidate in (entry.publisher, entry.family, entry.provider_model_identifier):
        if candidate is not None:
            for developer in LLMModelDeveloper:
                if developer.value in candidate.lower():
                    return developer
    return _PROVIDER_TO_DEVELOPER.get(entry.provider, LLMModelDeveloper.OTHER)


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogSyncNotFound:
    integration_id: str


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogSyncUnsupportedProvider:
    provider: LLMProvider


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogSyncAlreadyRunning:
    catalog_id: str
    work_token: str


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogSyncSuperseded:
    catalog_id: str
    superseding_work_token: str | None


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogSyncThrottled:
    retry_at: datetime.datetime


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogAutomaticRetryBlocked:
    pass


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogSyncNotStale:
    pass


def _sync_policy_failure(
    catalog_id: str, decision: IntegrationCatalogSyncPolicyDecision
) -> (
    IntegrationCatalogSyncAlreadyRunning
    | IntegrationCatalogSyncThrottled
    | IntegrationCatalogAutomaticRetryBlocked
    | IntegrationCatalogSyncNotStale
):
    match decision.denial_reason:
        case IntegrationCatalogSyncDenialReason.ALREADY_RUNNING:
            if decision.retry_at is None or decision.blocking_work_token is None:
                raise RuntimeError("Running sync policy is incomplete.")
            return IntegrationCatalogSyncAlreadyRunning(
                catalog_id, decision.blocking_work_token
            )
        case IntegrationCatalogSyncDenialReason.THROTTLED:
            if decision.retry_at is None:
                raise RuntimeError("Throttled sync policy did not provide retry time.")
            return IntegrationCatalogSyncThrottled(decision.retry_at)
        case IntegrationCatalogSyncDenialReason.AUTOMATIC_RETRY_BLOCKED:
            return IntegrationCatalogAutomaticRetryBlocked()
        case IntegrationCatalogSyncDenialReason.NOT_STALE:
            return IntegrationCatalogSyncNotStale()
        case None:
            raise RuntimeError("Allowed sync policy cannot be a failure.")
        case _:
            assert_never(decision.denial_reason)


@dataclasses.dataclass(frozen=True)
class SystemCatalogProjectionSummary:
    provider: LLMProvider
    catalog_id: str
    last_success_at: datetime.datetime | None
    visible_count: int
    hidden_count: int
    status: str = "succeeded"
    failure_code: str | None = None
    failure_message: str | None = None
    action_hint: str | None = None


class ModelCatalogEntryOutput(BaseModel):
    """One current exact model with server-owned normalized pricing."""

    id: str
    provider: LLMProvider
    provider_model_identifier: str
    display_name: str
    normalized_capabilities: ModelCapabilities
    supported_execution_options: list[ModelExecutionOptionId]
    lifecycle_status: LLMModelLifecycleStatus
    visibility_status: LLMCatalogEntryVisibility
    publisher: str | None
    family: str | None
    pricing: ModelPricingDefinition = Field(
        description="Server-normalized pricing definition"
    )
    source_metadata: dict[str, Any] | None
    projection_metadata: dict[str, Any] | None

    @classmethod
    def convert_from(cls, entry: LLMCatalogEntry) -> "ModelCatalogEntryOutput":
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
            pricing=entry.pricing,
            source_metadata=entry.source_metadata,
            projection_metadata=entry.projection_metadata,
        )


class ModelCatalogSyncStatusOutput(BaseModel):
    """Current operational state without work-token or data-revision exposure."""

    status: str
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    failure_code: str | None
    failure_message: str | None
    action_hint: str | None
    fetched_count: int
    matched_count: int
    skipped_count: int
    hidden_count: int

    @classmethod
    def convert_from(
        cls, status: LLMCatalogSyncStatus
    ) -> "ModelCatalogSyncStatusOutput":
        return cls(
            status=status.status.value,
            started_at=status.started_at,
            finished_at=status.finished_at,
            failure_code=status.failure_code,
            failure_message=status.failure_message,
            action_hint=status.action_hint,
            fetched_count=status.fetched_count,
            matched_count=status.matched_count,
            skipped_count=status.skipped_count,
            hidden_count=status.hidden_count,
        )


class SystemCatalogListItem(BaseModel):
    provider: LLMProvider
    catalog_id: str | None
    last_success_at: datetime.datetime | None
    visible_count: int
    hidden_count: int
    latest_sync: ModelCatalogSyncStatusOutput | None


class ModelCatalogEntryListOutput(BaseModel):
    catalog_id: str
    catalog_scope: LLMCatalogScope
    last_success_at: datetime.datetime | None
    latest_sync: ModelCatalogSyncStatusOutput | None
    stale: bool
    sync_available_at: datetime.datetime | None
    automatic_retry_blocked: bool
    entries: list[ModelCatalogEntryOutput]
    total: int
    limit: int
    offset: int


def _sync_policy_state(status: LLMCatalogSyncStatus | None) -> CatalogSyncState | None:
    if status is None:
        return None
    return CatalogSyncState(
        owner_id=status.owner_id,
        work_token=status.work_token,
        status=status.status,
        started_at=status.started_at,
        finished_at=status.finished_at,
        automatic_retry_blocked=CatalogRetryPolicy.from_diagnostics(
            status.diagnostics
        ).automatic_retry_blocked,
    )


@dataclasses.dataclass(frozen=True)
class ModelCatalogReadService:
    operations: Annotated[
        LLMCatalogOperationsRepository, Depends(LLMCatalogOperationsRepository)
    ]

    async def resolve_agent_model_selection(
        self, *, workspace_id: str, selection_input: AgentModelSelectionInput
    ) -> Result[AgentModelSelection, CatalogNotFound]:
        """Copy coherent exact entry facts and prices through existing predicates."""
        result = await self.operations.selectable_entry(
            integration_id=selection_input.llm_provider_integration_id,
            workspace_id=workspace_id,
            model_identifier=selection_input.model_identifier,
        )
        if result is None:
            return Failure(CatalogNotFound(selection_input.llm_provider_integration_id))
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
                pricing=entry.pricing,
                model_snapshot={
                    "source": "stored_catalog_projection",
                    "catalog_id": result.catalog.id,
                    "entry_id": entry.id,
                    "lifecycle_status": entry.lifecycle_status.value,
                },
                source_metadata=entry.source_metadata,
                last_refreshed_at=entry.updated_at,
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
        captured = await self.operations.read_page(
            integration_id=integration_id,
            workspace_id=workspace_id,
            search=search,
            limit=limit,
            offset=offset,
        )
        if captured is None:
            return Failure(CatalogNotFound(integration_id))
        page = captured.page
        policy = evaluate_integration_catalog_sync_policy(
            IntegrationCatalogSyncPolicyInput(
                trigger=IntegrationCatalogSyncTrigger.EXPLICIT,
                now=_utcnow(),
                last_success_at=page.catalog.last_success_at,
                latest_catalog_sync=_sync_policy_state(page.catalog.sync_status),
                latest_workspace_sync=_sync_policy_state(
                    captured.latest_workspace_sync
                ),
            )
        )
        return Success(
            ModelCatalogEntryListOutput(
                catalog_id=page.catalog.id,
                catalog_scope=page.catalog.scope,
                last_success_at=page.catalog.last_success_at,
                latest_sync=ModelCatalogSyncStatusOutput.convert_from(
                    page.catalog.sync_status
                )
                if page.catalog.sync_status is not None
                else None,
                stale=policy.stale,
                sync_available_at=policy.retry_at,
                automatic_retry_blocked=CatalogRetryPolicy.from_diagnostics(
                    page.catalog.sync_status.diagnostics
                    if page.catalog.sync_status is not None
                    else None
                ).automatic_retry_blocked,
                entries=[
                    ModelCatalogEntryOutput.convert_from(entry)
                    for entry in page.entries
                ],
                total=page.total,
                limit=limit,
                offset=offset,
            )
        )


@dataclasses.dataclass(frozen=True)
class SystemCatalogProjectionService:
    operations: Annotated[
        LLMCatalogOperationsRepository, Depends(LLMCatalogOperationsRepository)
    ]
    source_sync_service: Annotated[
        ModelMetadataSourceSyncService, Depends(ModelMetadataSourceSyncService)
    ]

    async def list_system_catalogs(self) -> list[SystemCatalogListItem]:
        states = await self.operations.read_system_catalogs(_SYSTEM_CATALOG_PROVIDERS)
        return [
            SystemCatalogListItem(
                provider=state.provider,
                catalog_id=state.catalog.id if state.catalog else None,
                last_success_at=state.catalog.last_success_at
                if state.catalog
                else None,
                visible_count=state.catalog.visible_count if state.catalog else 0,
                hidden_count=state.catalog.hidden_count if state.catalog else 0,
                latest_sync=ModelCatalogSyncStatusOutput.convert_from(
                    state.catalog.sync_status
                )
                if state.catalog and state.catalog.sync_status
                else None,
            )
            for state in states
        ]

    async def sync_system_catalogs(self) -> list[SystemCatalogProjectionSummary]:
        """Publish changed source and every affected system catalog together."""
        completed = True
        try:
            await self.source_sync_service.sync_current_source()
        except ModelMetadataSourceSyncBusy:
            completed = False
        states = await self.list_system_catalogs()
        return [
            SystemCatalogProjectionSummary(
                provider=state.provider,
                catalog_id=state.catalog_id,
                last_success_at=state.last_success_at,
                visible_count=state.visible_count,
                hidden_count=state.hidden_count,
                status="succeeded"
                if completed
                else state.latest_sync.status
                if state.latest_sync is not None
                else "running",
            )
            for state in states
            if state.catalog_id is not None
        ]

    async def sync_system_catalog(
        self, *, provider: LLMProvider
    ) -> SystemCatalogProjectionSummary:
        if provider not in _SYSTEM_CATALOG_PROVIDERS:
            raise ValueError("Unsupported system catalog provider.")
        summaries = await self.sync_system_catalogs()
        return next(item for item in summaries if item.provider == provider)


type IntegrationModelListing = Callable[
    [LLMProviderIntegrationWithSecrets, ListingClientFactories],
    Awaitable[ModelListingOutput],
]


async def provider_model_listing(
    integration: LLMProviderIntegrationWithSecrets, clients: ListingClientFactories
) -> ModelListingOutput:
    return await _list_provider_visible_models(integration, clients=clients)


def get_integration_model_listing() -> IntegrationModelListing:
    return provider_model_listing


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogProjectionService:
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
        preparation = await self.operations.begin_sync(
            integration_id=integration.id,
            provider=integration.provider,
            workspace_id=workspace_id,
            started_at=_utcnow(),
            trigger=trigger,
        )
        catalog, claim = preparation.catalog, preparation.claim
        if isinstance(claim, IntegrationCatalogSyncPolicyDecision):
            return Failure(_sync_policy_failure(catalog.id, claim))
        try:
            current = await self.operations.load_integration(integration_id)
            if current is None or current.workspace_id != workspace_id:
                raise ListingProviderError(
                    "The integration disappeared after synchronization started.",
                    automatic_retry_blocked=True,
                )
            if (
                current.catalog_configuration_version
                != claim.catalog_configuration_version
            ):
                raise ListingProviderError(
                    "The integration configuration changed after "
                    "synchronization started.",
                    automatic_retry_blocked=False,
                )
            integration = await self._refresh_oauth(current)
            if deterministic_failure:
                raise ListingProviderError(
                    "Deterministic user catalog listing failed.",
                    automatic_retry_blocked=True,
                )
            listing = deterministic_listing or await self.provider_listing(
                integration, self.listing_clients
            )
            for retry in range(2):
                source = await self.source_sync_service.get_current_source()
                entries = (
                    project_deterministic_integration_entries(
                        integration_id=integration.id,
                        provider=integration.provider,
                        listing=listing,
                        source=source,
                    )
                    if deterministic_listing is not None
                    else project_integration_replacement_entries(
                        integration_id=integration.id,
                        provider=integration.provider,
                        candidates=listing.models,
                        source=source,
                        provider_listing_source=listing.summary.source,
                    )
                )
                diagnostics = _projection_diagnostics(
                    entries=entries,
                    listing=listing,
                    context={
                        "integration_id": integration.id,
                        "trigger": trigger.value,
                    },
                )
                publication = await self.operations.publish(
                    catalog=catalog,
                    claim=claim,
                    entries=entries,
                    expected_source_models=projection_source_expectations(
                        provider=integration.provider,
                        candidates=listing.models,
                        source=source,
                    ),
                    expected_source_metadata=SourceProjectionMetadata(
                        source_key=source.source_key,
                        source_kind=source.source_kind,
                        collected_at=source.collected_at,
                    )
                    if source
                    else None,
                    diagnostics=diagnostics,
                    sync_diagnostics=diagnostics,
                    fetched_count=listing.summary.returned_count,
                    skipped_count=listing.summary.skipped_count,
                    finished_at=_utcnow(),
                )
                if isinstance(publication, CatalogPublicationSourceChanged):
                    if retry == 0:
                        continue
                    raise ListingProviderError(
                        "The model source changed during catalog preparation.",
                        automatic_retry_blocked=False,
                    )
                if isinstance(publication, CatalogPublicationSuperseded):
                    return Failure(
                        IntegrationCatalogSyncSuperseded(
                            catalog.id, publication.superseding_work_token
                        )
                    )
                return Success(
                    SystemCatalogProjectionSummary(
                        provider=integration.provider,
                        catalog_id=catalog.id,
                        last_success_at=publication.catalog.last_success_at,
                        visible_count=publication.visible_count,
                        hidden_count=publication.hidden_count,
                    )
                )
            raise AssertionError("Catalog publication retry boundary was exhausted.")
        except ListingProviderError as error:
            return Success(
                await self._record_listing_failure(
                    catalog=catalog,
                    work_token=claim.work_token,
                    integration=integration,
                    trigger=trigger,
                    error=error,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self.operations.fail_sync(
                CatalogSyncFailure(
                    catalog_id=catalog.id,
                    work_token=claim.work_token,
                    finished_at=_utcnow(),
                    failure_code=type(error).__name__,
                    failure_message=str(error),
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

    async def _refresh_oauth(
        self, integration: LLMProviderIntegrationWithSecrets
    ) -> LLMProviderIntegrationWithSecrets:
        if integration.provider == LLMProvider.CHATGPT_OAUTH:
            result = await ensure_runtime_tokens(
                integration=integration,
                persistence_repository=self.chatgpt_oauth_runtime_repository,
                client_factory=self.oauth_clients.chatgpt,
            )
            if result.success:
                return result.value
            match result.error:
                case ProviderRejected(reason=reason):
                    raise ListingProviderError(reason, automatic_retry_blocked=True)
                case ProviderUnavailable(reason=reason):
                    raise ListingProviderError(reason, automatic_retry_blocked=False)
                case _:
                    assert_never(result.error)
        if integration.provider == LLMProvider.KIMI_OAUTH:
            kimi_result = await ensure_kimi_runtime_tokens(
                integration=integration,
                persistence_repository=self.kimi_oauth_runtime_repository,
                client_factory=self.oauth_clients.kimi,
            )
            if kimi_result.success:
                return kimi_result.value
            match kimi_result.error:
                case KimiProviderRejected(reason=reason):
                    raise ListingProviderError(reason, automatic_retry_blocked=True)
                case KimiProviderUnavailable(reason=reason):
                    raise ListingProviderError(reason, automatic_retry_blocked=False)
                case _:
                    assert_never(kimi_result.error)
        if integration.provider == LLMProvider.XAI_OAUTH:
            xai_result = await ensure_xai_runtime_tokens(
                integration=integration,
                persistence_repository=self.xai_oauth_runtime_repository,
                client_factory=self.oauth_clients.xai,
            )
            if xai_result.success:
                return xai_result.value
            match xai_result.error:
                case (
                    XaiProviderRejected(reason=reason)
                    | XaiProviderEntitlementDenied(reason=reason)
                ):
                    raise ListingProviderError(reason, automatic_retry_blocked=True)
                case XaiProviderUnavailable(reason=reason):
                    raise ListingProviderError(reason, automatic_retry_blocked=False)
                case _:
                    assert_never(xai_result.error)
        return integration

    async def _record_listing_failure(
        self,
        *,
        catalog: LLMCatalog,
        work_token: str,
        integration: LLMProviderIntegrationWithSecrets,
        trigger: IntegrationCatalogSyncTrigger,
        error: ListingProviderError,
    ) -> SystemCatalogProjectionSummary:
        cause = error.__cause__
        failure_code = (
            error.failure_code
            if isinstance(error, XaiListingProviderError)
            else type(cause).__name__
            if cause
            else type(error).__name__
        )
        failure_message = (
            str(error)
            if isinstance(error, XaiListingProviderError)
            else str(cause or error)
        )
        action_hint = (
            "Check integration credentials and provider permissions."
            if error.automatic_retry_blocked
            else "Retry after the provider becomes available."
        )
        await self.operations.fail_sync(
            CatalogSyncFailure(
                catalog_id=catalog.id,
                work_token=work_token,
                finished_at=_utcnow(),
                failure_code=failure_code,
                failure_message=failure_message,
                action_hint=action_hint,
                diagnostics={
                    "integration_id": integration.id,
                    "failure_category": "user_catalog_credentials_or_permissions"
                    if error.automatic_retry_blocked
                    else "provider_transient_failure",
                    "automatic_retry_blocked": error.automatic_retry_blocked,
                    "retry_policy": "explicit_retry_or_integration_update_only"
                    if error.automatic_retry_blocked
                    else "throttled_backoff",
                    "trigger": trigger.value,
                },
            )
        )
        return SystemCatalogProjectionSummary(
            provider=integration.provider,
            catalog_id=catalog.id,
            last_success_at=catalog.last_success_at,
            visible_count=catalog.visible_count,
            hidden_count=catalog.hidden_count,
            status="failed",
            failure_code=failure_code,
            failure_message=failure_message,
            action_hint=action_hint,
        )


def _deterministic_listing_failure(
    integration: LLMProviderIntegrationWithSecrets,
) -> bool:
    return (
        parse_deterministic_fixture_variant(integration.name) == "deterministic-failure"
    )


def _deterministic_listing(
    integration: LLMProviderIntegrationWithSecrets,
) -> ModelListingOutput | None:
    variant = parse_deterministic_fixture_variant(integration.name)
    if variant is None:
        return None
    return build_deterministic_listing(
        variant=variant, provider=integration.provider, integration_id=integration.id
    )


async def _list_provider_visible_models(
    integration: LLMProviderIntegrationWithSecrets, *, clients: ListingClientFactories
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
    source: ModelMetadataSource | None,
) -> list[LLMCatalogEntryCreate]:
    """Preserve fixture capabilities while exercising normal exact pricing copies."""
    entries = project_integration_replacement_entries(
        integration_id=integration_id,
        provider=provider,
        candidates=listing.models,
        source=source,
        provider_listing_source=listing.summary.source,
    )
    return [
        dataclasses.replace(
            entry,
            normalized_capabilities=candidate.normalized_capabilities.model_dump(
                mode="json"
            ),
            projection_metadata={
                **(entry.projection_metadata or {}),
                "testenv_fixture": True,
                "freshness_rank": model_freshness_rank(candidate.model_identifier),
            },
        )
        for entry, candidate in zip(entries, listing.models, strict=True)
    ]


def _projection_diagnostics(
    *,
    entries: list[LLMCatalogEntryCreate],
    listing: ModelListingOutput | None,
    context: dict[str, Any],
) -> dict[str, Any]:
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
        "fetched_count": listing.summary.returned_count if listing else len(entries),
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
