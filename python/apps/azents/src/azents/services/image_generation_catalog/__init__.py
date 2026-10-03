"""Current image-generation catalogs with purpose-specific usability."""

import asyncio
import dataclasses
import datetime
from typing import Annotated, Literal, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.agent import AgentModelSelection, SelectableModelSettings
from azents.core.enums import LLMCatalogEntryVisibility, LLMProvider
from azents.core.image_generation_catalog import (
    image_generation_lifecycle_is_executable,
    image_generation_registry_entries_for_provider,
    image_generation_registry_entry,
)
from azents.core.image_generation_config import (
    ExplicitImageGenerationModel,
    InvalidImageGenerationModelConfig,
    MaintainedImageGenerationDefault,
    decode_image_generation_model_config,
)
from azents.core.llm_catalog_sync import (
    CatalogSyncState,
    IntegrationCatalogSyncDenialReason,
    IntegrationCatalogSyncPolicyDecision,
    IntegrationCatalogSyncPolicyInput,
    IntegrationCatalogSyncTrigger,
    evaluate_integration_catalog_sync_policy,
)
from azents.repos.image_generation_catalog_operations import (
    ImageGenerationCatalogOperationsRepository,
)
from azents.repos.llm_catalog.data import (
    CatalogNotFound,
    CatalogRetryPolicy,
    ImageGenerationCatalogEntryCreate,
    ImageGenerationCatalogEntryList,
    LLMCatalogSyncStatus,
)
from azents.repos.llm_catalog_operations import CatalogSyncFailure
from azents.services.llm_catalog import (
    IntegrationCatalogAutomaticRetryBlocked,
    IntegrationCatalogSyncAlreadyRunning,
    IntegrationCatalogSyncNotStale,
    IntegrationCatalogSyncThrottled,
    IntegrationCatalogSyncUnsupportedProvider,
    SystemCatalogProjectionSummary,
)
from azents.services.model_listing.providers import (
    ListingClientFactories,
    ListingProviderError,
    create_listing_client_factories,
    list_openai_image_generation_models_for_integration,
)

from .data import (
    ImageGenerationCatalogEntryOutput,
    ImageGenerationCatalogSyncStatusOutput,
    ImageGenerationModelCatalogOutput,
)

_DEFAULT_IMAGE_GENERATION_PROVIDERS = frozenset(
    {
        LLMProvider.OPENAI,
        LLMProvider.CHATGPT_OAUTH,
        LLMProvider.XAI,
        LLMProvider.XAI_OAUTH,
    }
)
_EXPLICIT_IMAGE_SELECTION_PROVIDERS = frozenset({LLMProvider.OPENAI})


def image_generation_default_available(
    *, provider: LLMProvider, integration_enabled: bool
) -> bool:
    return integration_enabled and provider in _DEFAULT_IMAGE_GENERATION_PROVIDERS


def image_generation_explicit_selection_supported(provider: LLMProvider) -> bool:
    return provider in _EXPLICIT_IMAGE_SELECTION_PROVIDERS


def default_only_image_generation_catalog(
    *, provider: LLMProvider, integration_enabled: bool
) -> ImageGenerationModelCatalogOutput:
    """Maintain the established synthetic default-only availability contract."""
    return ImageGenerationModelCatalogOutput(
        default_available=image_generation_default_available(
            provider=provider, integration_enabled=integration_enabled
        ),
        explicit_selection_supported=False,
        catalog_id=None,
        last_success_at=None,
        latest_sync=None,
        stale=False,
        usable=True,
        sync_available_at=None,
        automatic_retry_blocked=False,
        entries=[],
        total=0,
    )


@dataclasses.dataclass(frozen=True)
class ImageGenerationCatalogSyncNotFound:
    integration_id: str


@dataclasses.dataclass(frozen=True)
class ImageGenerationCatalogSyncSuperseded:
    catalog_id: str
    superseding_work_token: str | None
    current_configuration_version: int


@dataclasses.dataclass(frozen=True)
class ImageGenerationRuntimeConfigurationError:
    reason: Literal[
        "integration_disabled",
        "explicit_selection_unsupported",
        "catalog_unavailable",
        "catalog_unusable",
        "model_unavailable",
        "provider_model_mismatch",
    ]
    integration_id: str
    model_identifier: str | None


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


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
                raise RuntimeError("Running image sync policy is incomplete.")
            return IntegrationCatalogSyncAlreadyRunning(
                catalog_id, decision.blocking_work_token
            )
        case IntegrationCatalogSyncDenialReason.THROTTLED:
            if decision.retry_at is None:
                raise RuntimeError("Throttled image sync policy is incomplete.")
            return IntegrationCatalogSyncThrottled(decision.retry_at)
        case IntegrationCatalogSyncDenialReason.AUTOMATIC_RETRY_BLOCKED:
            return IntegrationCatalogAutomaticRetryBlocked()
        case IntegrationCatalogSyncDenialReason.NOT_STALE:
            return IntegrationCatalogSyncNotStale()
        case None:
            raise RuntimeError("Allowed image sync policy cannot be a failure.")
        case _:
            assert_never(decision.denial_reason)


def _status_output(
    status: LLMCatalogSyncStatus | None,
) -> ImageGenerationCatalogSyncStatusOutput | None:
    if status is None:
        return None
    return ImageGenerationCatalogSyncStatusOutput(
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


def _catalog_output(
    *,
    integration_provider: LLMProvider,
    integration_enabled: bool,
    page: ImageGenerationCatalogEntryList,
    policy: IntegrationCatalogSyncPolicyDecision,
) -> ImageGenerationModelCatalogOutput:
    return ImageGenerationModelCatalogOutput(
        default_available=image_generation_default_available(
            provider=integration_provider, integration_enabled=integration_enabled
        ),
        explicit_selection_supported=image_generation_explicit_selection_supported(
            integration_provider
        ),
        catalog_id=page.catalog.id,
        last_success_at=page.catalog.last_success_at,
        latest_sync=_status_output(page.catalog.sync_status),
        stale=policy.stale,
        usable=page.catalog.image_usable is True,
        sync_available_at=policy.retry_at,
        automatic_retry_blocked=CatalogRetryPolicy.from_diagnostics(
            page.catalog.sync_status.diagnostics
            if page.catalog.sync_status is not None
            else None
        ).automatic_retry_blocked,
        entries=[
            ImageGenerationCatalogEntryOutput(
                id=entry.id,
                provider=entry.provider,
                provider_model_identifier=entry.provider_model_identifier,
                display_name=entry.display_name,
                description=entry.description,
                recommendation_rank=entry.recommendation_rank,
                lifecycle_status=entry.lifecycle_status,
                visibility_status=entry.visibility_status,
                source_metadata=entry.source_metadata,
                projection_metadata=entry.projection_metadata,
            )
            for entry in page.entries
        ],
        total=page.total,
    )


@dataclasses.dataclass(frozen=True)
class ImageGenerationCatalogService:
    operations: Annotated[
        ImageGenerationCatalogOperationsRepository,
        Depends(ImageGenerationCatalogOperationsRepository),
    ]
    listing_clients: Annotated[
        ListingClientFactories, Depends(create_listing_client_factories)
    ]

    async def read(
        self, *, integration_id: str, workspace_id: str
    ) -> Result[ImageGenerationModelCatalogOutput, CatalogNotFound]:
        captured = await self.operations.read(
            integration_id=integration_id, workspace_id=workspace_id
        )
        if captured is None:
            return Failure(CatalogNotFound(integration_id))
        integration, page = captured.integration, captured.page
        if page is None:
            return Success(
                default_only_image_generation_catalog(
                    provider=integration.provider,
                    integration_enabled=integration.enabled,
                )
            )
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
            _catalog_output(
                integration_provider=integration.provider,
                integration_enabled=integration.enabled,
                page=page,
                policy=policy,
            )
        )

    async def sync(
        self,
        *,
        integration_id: str,
        workspace_id: str,
        trigger: IntegrationCatalogSyncTrigger = IntegrationCatalogSyncTrigger.EXPLICIT,
    ) -> Result[
        SystemCatalogProjectionSummary,
        ImageGenerationCatalogSyncNotFound
        | IntegrationCatalogSyncUnsupportedProvider
        | IntegrationCatalogSyncAlreadyRunning
        | ImageGenerationCatalogSyncSuperseded
        | IntegrationCatalogSyncThrottled
        | IntegrationCatalogAutomaticRetryBlocked
        | IntegrationCatalogSyncNotStale,
    ]:
        integration = await self.operations.load_integration(integration_id)
        if integration is None or integration.workspace_id != workspace_id:
            return Failure(ImageGenerationCatalogSyncNotFound(integration_id))
        if not image_generation_explicit_selection_supported(integration.provider):
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
            listing_integration = await self.operations.load_listing_integration(
                integration_id
            )
            if (
                listing_integration is None
                or listing_integration.workspace_id != workspace_id
            ):
                raise ListingProviderError(
                    "The integration disappeared after synchronization started.",
                    automatic_retry_blocked=True,
                )
            listing = await list_openai_image_generation_models_for_integration(
                listing_integration, clients=self.listing_clients
            )
            visible_ids = set(listing.provider_model_identifiers)
            entries = [
                ImageGenerationCatalogEntryCreate(
                    provider=registry.provider,
                    provider_model_identifier=registry.provider_model_identifier,
                    display_name=registry.display_name,
                    description=registry.description,
                    recommendation_rank=registry.recommendation_rank,
                    lifecycle_status=registry.lifecycle_status,
                    visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
                    provider_integration_id=integration.id,
                    source_metadata={
                        "provider_listing_source": listing.source,
                        "provider_fetched_at": listing.fetched_at.isoformat(),
                    },
                    projection_metadata=None,
                    hidden_reason=None,
                )
                for registry in image_generation_registry_entries_for_provider(
                    integration.provider
                )
                if registry.provider_model_identifier in visible_ids
            ]
            diagnostics = {
                "catalog_purpose": "image_generation",
                "integration_id": integration.id,
                "trigger": trigger.value,
            }
            publication = await self.operations.publish(
                catalog=catalog,
                claim=claim,
                entries=entries,
                diagnostics=diagnostics,
                sync_diagnostics=diagnostics,
                fetched_count=len(listing.provider_model_identifiers),
                finished_at=_utcnow(),
                trigger=trigger,
            )
            if not publication.published:
                return Failure(
                    ImageGenerationCatalogSyncSuperseded(
                        catalog.id,
                        publication.superseding_work_token,
                        publication.current_configuration_version,
                    )
                )
            return Success(
                SystemCatalogProjectionSummary(
                    provider=integration.provider,
                    catalog_id=catalog.id,
                    last_success_at=publication.last_success_at,
                    visible_count=len(entries),
                    hidden_count=0,
                )
            )
        except ListingProviderError as error:
            cause = error.__cause__
            failure_code = type(cause).__name__ if cause else type(error).__name__
            action_hint = (
                "Check integration credentials and provider permissions."
                if error.automatic_retry_blocked
                else "Retry after the provider becomes available."
            )
            await self.operations.fail_sync(
                CatalogSyncFailure(
                    catalog_id=catalog.id,
                    work_token=claim.work_token,
                    finished_at=_utcnow(),
                    failure_code=failure_code,
                    failure_message=str(error),
                    action_hint=action_hint,
                    diagnostics={
                        "catalog_purpose": "image_generation",
                        "integration_id": integration.id,
                        "failure_category": "credentials_or_permissions"
                        if error.automatic_retry_blocked
                        else "provider_transient_failure",
                        "automatic_retry_blocked": error.automatic_retry_blocked,
                        "trigger": trigger.value,
                    },
                )
            )
            return Success(
                SystemCatalogProjectionSummary(
                    provider=integration.provider,
                    catalog_id=catalog.id,
                    last_success_at=catalog.last_success_at,
                    visible_count=catalog.visible_count,
                    hidden_count=catalog.hidden_count,
                    status="failed",
                    failure_code=failure_code,
                    failure_message=str(error),
                    action_hint=action_hint,
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
                        "catalog_purpose": "image_generation",
                        "integration_id": integration.id,
                        "failure_category": "catalog_service_failure",
                        "automatic_retry_blocked": False,
                        "trigger": trigger.value,
                    },
                )
            )
            raise

    async def validate_option(
        self,
        *,
        workspace_id: str,
        selection: AgentModelSelection,
        settings: SelectableModelSettings,
    ) -> list[str]:
        image_tool = next(
            (
                tool
                for tool in settings.builtin_tools
                if tool.name == "image_generation"
            ),
            None,
        )
        if image_tool is None:
            return []
        try:
            image_config = decode_image_generation_model_config(image_tool.config)
        except InvalidImageGenerationModelConfig as error:
            return [str(error)]
        registry_entry = None
        lookup_identifier = None
        if isinstance(image_config, ExplicitImageGenerationModel):
            registry_entry = image_generation_registry_entry(
                provider=selection.provider,
                provider_model_identifier=image_config.model_identifier,
            )
            if registry_entry is not None and image_generation_lifecycle_is_executable(
                registry_entry.lifecycle_status
            ):
                lookup_identifier = image_config.model_identifier
        authority = await self.operations.option_authority(
            integration_id=selection.llm_provider_integration_id,
            workspace_id=workspace_id,
            expected_provider=selection.provider,
            model_identifier=lookup_identifier,
        )
        integration = authority.integration
        if integration is None or integration.workspace_id != workspace_id:
            return ["The image generation provider integration was not found."]
        if integration.provider != selection.provider:
            return [
                "The image generation provider does not match the conversation model."
            ]
        if not integration.enabled:
            return ["Enable the provider integration before using image generation."]
        if isinstance(image_config, MaintainedImageGenerationDefault):
            return (
                []
                if image_generation_default_available(
                    provider=integration.provider,
                    integration_enabled=integration.enabled,
                )
                else [
                    "This provider does not support maintained-default "
                    "image generation."
                ]
            )
        if not image_generation_explicit_selection_supported(integration.provider):
            return [
                "This provider supports only the maintained image generation default."
            ]
        if registry_entry is None or not image_generation_lifecycle_is_executable(
            registry_entry.lifecycle_status
        ):
            return ["Choose an available image generation model or use the default."]
        if authority.entry is None:
            return [
                "Refresh the image model catalog, choose an available model, "
                "or use the default."
            ]
        return []

    async def validate_runtime(
        self,
        *,
        integration_id: str,
        workspace_id: str,
        provider: LLMProvider,
        integration_enabled: bool,
        image_generation_supported: bool,
        settings: SelectableModelSettings,
    ) -> ImageGenerationRuntimeConfigurationError | None:
        image_tool = next(
            (
                tool
                for tool in settings.builtin_tools
                if tool.name == "image_generation"
            ),
            None,
        )
        if image_tool is None:
            return None
        try:
            image_config = decode_image_generation_model_config(image_tool.config)
        except InvalidImageGenerationModelConfig:
            return ImageGenerationRuntimeConfigurationError(
                "model_unavailable", integration_id, None
            )
        model_identifier = (
            image_config.model_identifier
            if isinstance(image_config, ExplicitImageGenerationModel)
            else None
        )
        if not image_generation_supported:
            return ImageGenerationRuntimeConfigurationError(
                "model_unavailable", integration_id, model_identifier
            )
        if not integration_enabled:
            return ImageGenerationRuntimeConfigurationError(
                "integration_disabled", integration_id, model_identifier
            )
        if isinstance(image_config, MaintainedImageGenerationDefault):
            if image_generation_default_available(
                provider=provider, integration_enabled=integration_enabled
            ):
                return None
            return ImageGenerationRuntimeConfigurationError(
                "catalog_unavailable", integration_id, None
            )
        if not image_generation_explicit_selection_supported(provider):
            return ImageGenerationRuntimeConfigurationError(
                "explicit_selection_unsupported",
                integration_id,
                image_config.model_identifier,
            )
        registry = image_generation_registry_entry(
            provider=provider, provider_model_identifier=image_config.model_identifier
        )
        if registry is None or not image_generation_lifecycle_is_executable(
            registry.lifecycle_status
        ):
            return ImageGenerationRuntimeConfigurationError(
                "model_unavailable", integration_id, image_config.model_identifier
            )
        authority = await self.operations.runtime_authority(
            integration_id=integration_id,
            workspace_id=workspace_id,
            model_identifier=image_config.model_identifier,
        )
        if authority.page is None or authority.page.catalog.last_success_at is None:
            return ImageGenerationRuntimeConfigurationError(
                "catalog_unavailable", integration_id, image_config.model_identifier
            )
        if authority.page.catalog.image_usable is not True:
            return ImageGenerationRuntimeConfigurationError(
                "catalog_unusable", integration_id, image_config.model_identifier
            )
        if authority.entry is None:
            return ImageGenerationRuntimeConfigurationError(
                "model_unavailable", integration_id, image_config.model_identifier
            )
        if authority.entry.entry.provider != provider:
            return ImageGenerationRuntimeConfigurationError(
                "provider_model_mismatch", integration_id, image_config.model_identifier
            )
        return None
