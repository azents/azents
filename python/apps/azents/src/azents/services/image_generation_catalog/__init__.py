"""Stored image-generation catalog service."""

import dataclasses
import datetime
from typing import Annotated, Literal, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.agent import AgentModelSelection, SelectableModelSettings
from azents.core.enums import (
    LLMCatalogEntryVisibility,
    LLMProvider,
)
from azents.core.image_generation_catalog import (
    IMAGE_GENERATION_MODEL_REGISTRY_REVISION,
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
    CatalogSyncAttemptState,
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
    LLMCatalogSyncAttempt,
)
from azents.repos.llm_catalog_operations import CatalogAttemptFailure
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
    ImageGenerationCatalogAttemptOutput,
    ImageGenerationCatalogEntryOutput,
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
    *,
    provider: LLMProvider,
    integration_enabled: bool,
) -> bool:
    """Return whether provider-default image generation may be dispatched."""
    return integration_enabled and provider in _DEFAULT_IMAGE_GENERATION_PROVIDERS


def image_generation_explicit_selection_supported(provider: LLMProvider) -> bool:
    """Return whether a provider has a verified explicit model visibility source."""
    return provider in _EXPLICIT_IMAGE_SELECTION_PROVIDERS


def default_only_image_generation_catalog(
    *,
    provider: LLMProvider,
    integration_enabled: bool,
    current_configuration_version: int,
) -> ImageGenerationModelCatalogOutput:
    """Build a no-discovery response for providers limited to maintained defaults."""
    return ImageGenerationModelCatalogOutput(
        default_available=image_generation_default_available(
            provider=provider,
            integration_enabled=integration_enabled,
        ),
        explicit_selection_supported=False,
        catalog_id=None,
        snapshot_id=None,
        snapshot_configuration_version=None,
        current_configuration_version=current_configuration_version,
        snapshot_created_at=None,
        latest_attempt=None,
        stale=False,
        generation_current=True,
        sync_available_at=None,
        automatic_retry_blocked=False,
        entries=[],
        total=0,
    )


@dataclasses.dataclass(frozen=True)
class ImageGenerationCatalogSyncNotFound:
    """Image catalog synchronization target was not found."""

    integration_id: str


@dataclasses.dataclass(frozen=True)
class ImageGenerationCatalogSyncSuperseded:
    """Image catalog result was fenced by a newer attempt or configuration."""

    catalog_id: str
    superseding_attempt_id: str | None
    current_configuration_version: int


@dataclasses.dataclass(frozen=True)
class ImageGenerationRuntimeConfigurationError:
    """Safe non-retryable image-generation runtime configuration error."""

    reason: Literal[
        "integration_disabled",
        "explicit_selection_unsupported",
        "catalog_unavailable",
        "catalog_generation_mismatch",
        "model_unavailable",
        "provider_model_mismatch",
    ]
    integration_id: str
    model_identifier: str | None


def _utcnow() -> datetime.datetime:
    """Return current UTC time."""
    return datetime.datetime.now(datetime.UTC)


def _sync_policy_attempt(
    attempt: LLMCatalogSyncAttempt | None,
) -> CatalogSyncAttemptState | None:
    """Convert persisted attempt state to shared synchronization policy input."""
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


def _sync_policy_failure(
    catalog_id: str,
    decision: IntegrationCatalogSyncPolicyDecision,
) -> (
    IntegrationCatalogSyncAlreadyRunning
    | IntegrationCatalogSyncThrottled
    | IntegrationCatalogAutomaticRetryBlocked
    | IntegrationCatalogSyncNotStale
):
    """Convert shared synchronization policy denial to a service error."""
    match decision.denial_reason:
        case IntegrationCatalogSyncDenialReason.ALREADY_RUNNING:
            if decision.retry_at is None or decision.blocking_attempt_id is None:
                raise RuntimeError("Running image sync policy is incomplete.")
            return IntegrationCatalogSyncAlreadyRunning(
                catalog_id=catalog_id,
                attempt_id=decision.blocking_attempt_id,
            )
        case IntegrationCatalogSyncDenialReason.THROTTLED:
            if decision.retry_at is None:
                raise RuntimeError("Throttled image sync policy is incomplete.")
            return IntegrationCatalogSyncThrottled(retry_at=decision.retry_at)
        case IntegrationCatalogSyncDenialReason.AUTOMATIC_RETRY_BLOCKED:
            return IntegrationCatalogAutomaticRetryBlocked()
        case IntegrationCatalogSyncDenialReason.NOT_STALE:
            return IntegrationCatalogSyncNotStale()
        case None:
            raise RuntimeError("Allowed image sync policy cannot be a failure.")
        case _:
            assert_never(decision.denial_reason)


def _attempt_output(
    attempt: LLMCatalogSyncAttempt | None,
) -> ImageGenerationCatalogAttemptOutput | None:
    """Project one stored attempt without provider secrets or payloads."""
    if attempt is None:
        return None
    return ImageGenerationCatalogAttemptOutput(
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


def _catalog_output(
    *,
    integration_provider: LLMProvider,
    integration_enabled: bool,
    page: ImageGenerationCatalogEntryList,
    policy: IntegrationCatalogSyncPolicyDecision,
) -> ImageGenerationModelCatalogOutput:
    """Project stored image catalog state into its public service contract."""
    retry_policy = CatalogRetryPolicy.from_diagnostics(
        page.latest_attempt.diagnostics if page.latest_attempt is not None else None
    )
    generation_current = (
        page.snapshot_catalog_configuration_version
        == page.current_integration_catalog_configuration_version
        and page.catalog.current_snapshot_id is not None
    )
    return ImageGenerationModelCatalogOutput(
        default_available=image_generation_default_available(
            provider=integration_provider,
            integration_enabled=integration_enabled,
        ),
        explicit_selection_supported=image_generation_explicit_selection_supported(
            integration_provider
        ),
        catalog_id=page.catalog.id,
        snapshot_id=page.catalog.current_snapshot_id,
        snapshot_configuration_version=(page.snapshot_catalog_configuration_version),
        current_configuration_version=(
            page.current_integration_catalog_configuration_version
        ),
        snapshot_created_at=page.current_snapshot_created_at,
        latest_attempt=_attempt_output(page.latest_attempt),
        stale=policy.stale,
        generation_current=generation_current,
        sync_available_at=policy.retry_at,
        automatic_retry_blocked=retry_policy.automatic_retry_blocked,
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
    """Read and synchronize stored image-generation model catalogs."""

    operations: Annotated[
        ImageGenerationCatalogOperationsRepository,
        Depends(ImageGenerationCatalogOperationsRepository),
    ]
    listing_clients: Annotated[
        ListingClientFactories, Depends(create_listing_client_factories)
    ]

    async def read(
        self,
        *,
        integration_id: str,
        workspace_id: str,
    ) -> Result[ImageGenerationModelCatalogOutput, CatalogNotFound]:
        """Read stored image model availability without calling the provider."""
        snapshot = await self.operations.read(
            integration_id=integration_id, workspace_id=workspace_id
        )
        if snapshot is None:
            return Failure(CatalogNotFound(integration_id=integration_id))
        integration = snapshot.integration
        page = snapshot.page
        if page is None:
            return Success(
                default_only_image_generation_catalog(
                    provider=integration.provider,
                    integration_enabled=integration.enabled,
                    current_configuration_version=(
                        integration.catalog_configuration_version
                    ),
                )
            )
        latest_workspace_attempt = snapshot.latest_workspace_attempt
        policy = evaluate_integration_catalog_sync_policy(
            policy_input=IntegrationCatalogSyncPolicyInput(
                trigger=IntegrationCatalogSyncTrigger.EXPLICIT,
                now=_utcnow(),
                current_snapshot_created_at=page.current_snapshot_created_at,
                latest_catalog_attempt=_sync_policy_attempt(page.latest_attempt),
                latest_workspace_attempt=_sync_policy_attempt(latest_workspace_attempt),
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
        """Synchronize one OpenAI API-key image-generation catalog."""
        integration = await self.operations.load_integration(integration_id)
        if integration is None or integration.workspace_id != workspace_id:
            return Failure(ImageGenerationCatalogSyncNotFound(integration_id))
        if not image_generation_explicit_selection_supported(integration.provider):
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
        )
        catalog = preparation.catalog
        claim = preparation.claim
        if isinstance(claim, IntegrationCatalogSyncPolicyDecision):
            return Failure(_sync_policy_failure(catalog.id, claim))
        attempt_id = claim.attempt_id
        integration = await self.operations.load_listing_integration(integration_id)
        if integration is None or integration.workspace_id != workspace_id:
            return Failure(ImageGenerationCatalogSyncNotFound(integration_id))
        try:
            listing = await list_openai_image_generation_models_for_integration(
                integration, clients=self.listing_clients
            )
            visible_ids = set(listing.provider_model_identifiers)
            entries = [
                ImageGenerationCatalogEntryCreate(
                    provider=registry_entry.provider,
                    provider_model_identifier=(
                        registry_entry.provider_model_identifier
                    ),
                    display_name=registry_entry.display_name,
                    description=registry_entry.description,
                    recommendation_rank=registry_entry.recommendation_rank,
                    lifecycle_status=registry_entry.lifecycle_status,
                    visibility_status=LLMCatalogEntryVisibility.SELECTABLE,
                    provider_integration_id=integration.id,
                    source_metadata={
                        "provider_listing_source": listing.source,
                        "provider_fetched_at": listing.fetched_at.isoformat(),
                    },
                    projection_metadata={
                        "registry_revision": (IMAGE_GENERATION_MODEL_REGISTRY_REVISION),
                    },
                    hidden_reason=None,
                )
                for registry_entry in image_generation_registry_entries_for_provider(
                    integration.provider
                )
                if registry_entry.provider_model_identifier in visible_ids
            ]
            publication = await self.operations.publish(
                catalog=catalog,
                attempt_id=attempt_id,
                entries=entries,
                candidate_diagnostics={
                    "catalog_purpose": "image_generation",
                    "integration_id": integration.id,
                    "registry_revision": IMAGE_GENERATION_MODEL_REGISTRY_REVISION,
                },
                attempt_diagnostics={
                    "catalog_purpose": "image_generation",
                    "integration_id": integration.id,
                    "registry_revision": IMAGE_GENERATION_MODEL_REGISTRY_REVISION,
                    "trigger": trigger.value,
                },
                fetched_count=len(listing.provider_model_identifiers),
                finished_at=_utcnow(),
                trigger=trigger,
            )
            if publication.snapshot_id is None:
                return Failure(
                    ImageGenerationCatalogSyncSuperseded(
                        catalog_id=catalog.id,
                        superseding_attempt_id=publication.superseding_attempt_id,
                        current_configuration_version=(
                            publication.current_catalog_configuration_version
                        ),
                    )
                )
            return Success(
                SystemCatalogProjectionSummary(
                    provider=integration.provider,
                    catalog_id=catalog.id,
                    snapshot_id=publication.snapshot_id,
                    visible_count=len(entries),
                    hidden_count=0,
                )
            )
        except ListingProviderError as exc:
            cause = exc.__cause__
            failure_code = type(cause).__name__ if cause else type(exc).__name__
            action_hint = (
                "Check integration credentials and provider permissions."
                if exc.automatic_retry_blocked
                else "Retry after the provider becomes available."
            )
            await self.operations.fail_attempt(
                CatalogAttemptFailure(
                    attempt_id=attempt_id,
                    finished_at=_utcnow(),
                    failure_code=failure_code,
                    failure_message=str(exc),
                    action_hint=action_hint,
                    diagnostics={
                        "catalog_purpose": "image_generation",
                        "integration_id": integration.id,
                        "failure_category": (
                            "credentials_or_permissions"
                            if exc.automatic_retry_blocked
                            else "provider_transient_failure"
                        ),
                        "automatic_retry_blocked": exc.automatic_retry_blocked,
                        "trigger": trigger.value,
                    },
                )
            )
            return Success(
                SystemCatalogProjectionSummary(
                    provider=integration.provider,
                    catalog_id=catalog.id,
                    snapshot_id=catalog.current_snapshot_id,
                    visible_count=0,
                    hidden_count=0,
                    status="failed",
                    failure_code=failure_code,
                    failure_message=str(exc),
                    action_hint=action_hint,
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
        """Validate one enabled image-generation setting against stored authority."""
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
        except InvalidImageGenerationModelConfig as exc:
            return [str(exc)]
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
            if image_generation_default_available(
                provider=integration.provider,
                integration_enabled=integration.enabled,
            ):
                return []
            return [
                "This provider does not support maintained-default image generation."
            ]
        if not image_generation_explicit_selection_supported(integration.provider):
            return [
                "This provider supports only the maintained image generation default."
            ]
        if registry_entry is None or not image_generation_lifecycle_is_executable(
            registry_entry.lifecycle_status
        ):
            return ["Choose an available image generation model or use the default."]
        entry = authority.entry
        if entry is None:
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
        """Repeat explicit image-pin validation immediately before dispatch."""
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
                reason="model_unavailable",
                integration_id=integration_id,
                model_identifier=None,
            )
        if not image_generation_supported:
            return ImageGenerationRuntimeConfigurationError(
                reason="model_unavailable",
                integration_id=integration_id,
                model_identifier=(
                    image_config.model_identifier
                    if isinstance(image_config, ExplicitImageGenerationModel)
                    else None
                ),
            )
        if not integration_enabled:
            return ImageGenerationRuntimeConfigurationError(
                reason="integration_disabled",
                integration_id=integration_id,
                model_identifier=(
                    image_config.model_identifier
                    if isinstance(image_config, ExplicitImageGenerationModel)
                    else None
                ),
            )
        if isinstance(image_config, MaintainedImageGenerationDefault):
            if image_generation_default_available(
                provider=provider,
                integration_enabled=integration_enabled,
            ):
                return None
            return ImageGenerationRuntimeConfigurationError(
                reason="catalog_unavailable",
                integration_id=integration_id,
                model_identifier=None,
            )
        if not image_generation_explicit_selection_supported(provider):
            return ImageGenerationRuntimeConfigurationError(
                reason="explicit_selection_unsupported",
                integration_id=integration_id,
                model_identifier=image_config.model_identifier,
            )
        registry_entry = image_generation_registry_entry(
            provider=provider,
            provider_model_identifier=image_config.model_identifier,
        )
        if registry_entry is None or not image_generation_lifecycle_is_executable(
            registry_entry.lifecycle_status
        ):
            return ImageGenerationRuntimeConfigurationError(
                reason="model_unavailable",
                integration_id=integration_id,
                model_identifier=image_config.model_identifier,
            )
        authority = await self.operations.runtime_authority(
            integration_id=integration_id,
            workspace_id=workspace_id,
            model_identifier=image_config.model_identifier,
        )
        page = authority.page
        if page is None or page.catalog.current_snapshot_id is None:
            return ImageGenerationRuntimeConfigurationError(
                reason="catalog_unavailable",
                integration_id=integration_id,
                model_identifier=image_config.model_identifier,
            )
        if (
            page.snapshot_catalog_configuration_version
            != page.current_integration_catalog_configuration_version
        ):
            return ImageGenerationRuntimeConfigurationError(
                reason="catalog_generation_mismatch",
                integration_id=integration_id,
                model_identifier=image_config.model_identifier,
            )
        entry = authority.entry
        if entry is None:
            return ImageGenerationRuntimeConfigurationError(
                reason="model_unavailable",
                integration_id=integration_id,
                model_identifier=image_config.model_identifier,
            )
        if entry.entry.provider != provider:
            return ImageGenerationRuntimeConfigurationError(
                reason="provider_model_mismatch",
                integration_id=integration_id,
                model_identifier=image_config.model_identifier,
            )
        return None
