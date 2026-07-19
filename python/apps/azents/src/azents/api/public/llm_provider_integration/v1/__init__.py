"""LLM Provider Integration v1 Public API.

Workspace-scoped LLM provider integration CRUD endpoints.
"""

import datetime
import logging
from email.utils import format_datetime
from textwrap import dedent
from typing import Annotated, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.auth.permissions import Permissions
from azents.core.credentials import PROVIDER_SECRET_TYPES
from azents.core.enums import LLMCatalogScope, LLMProvider
from azents.core.llm_catalog import INTEGRATION_SCOPED_CATALOG_PROVIDERS
from azents.core.llm_catalog_sync import IntegrationCatalogSyncTrigger
from azents.repos.llm_catalog.data import CatalogNotFound
from azents.repos.llm_provider_integration.data import NotFound
from azents.services.llm_catalog import (
    IntegrationCatalogAutomaticRetryBlocked,
    IntegrationCatalogProjectionService,
    IntegrationCatalogSyncAlreadyRunning,
    IntegrationCatalogSyncNotFound,
    IntegrationCatalogSyncNotStale,
    IntegrationCatalogSyncSuperseded,
    IntegrationCatalogSyncThrottled,
    IntegrationCatalogSyncUnsupportedProvider,
    ModelCatalogReadService,
)
from azents.services.llm_provider_integration import LLMProviderIntegrationService
from azents.services.llm_provider_integration.data import (
    LLMProviderIntegrationCreateInput,
    NotBelongToWorkspace,
)
from azents.services.subscription_usage.data import (
    SubscriptionUsageNotFound,
    SubscriptionUsageNotInWorkspace,
    SubscriptionUsageUnsupportedProvider,
)
from azents.services.subscription_usage.service import SubscriptionUsageService
from azents.testing.deterministic_model_listing import (
    parse_deterministic_fixture_variant,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    LLMProviderCapabilityListResponse,
    LLMProviderCapabilityResponse,
    LLMProviderIntegrationCreateRequest,
    LLMProviderIntegrationListResponse,
    LLMProviderIntegrationResponse,
    LLMProviderIntegrationUpdateRequest,
    ModelCatalogEntryListResponse,
    ModelCatalogSyncResponse,
    SubscriptionUsageResponse,
    convert_subscription_usage_response,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Default provider display names
_PROVIDER_DISPLAY_NAMES: dict[LLMProvider, str] = {
    LLMProvider.OPENAI: "OpenAI",
    LLMProvider.ANTHROPIC: "Anthropic",
    LLMProvider.GOOGLE_GEMINI: "Google Gemini",
    LLMProvider.AWS_BEDROCK: "AWS Bedrock",
    LLMProvider.GOOGLE_VERTEX_AI: "Google Vertex AI",
    LLMProvider.CHATGPT_OAUTH: "ChatGPT OAuth",
    LLMProvider.XAI: "xAI API key",
    LLMProvider.XAI_OAUTH: "xAI Grok OAuth",
}

_BASE_AVAILABLE_PROVIDERS: tuple[LLMProvider, ...] = (
    LLMProvider.OPENAI,
    LLMProvider.ANTHROPIC,
    LLMProvider.GOOGLE_GEMINI,
    LLMProvider.AWS_BEDROCK,
    LLMProvider.GOOGLE_VERTEX_AI,
    LLMProvider.CHATGPT_OAUTH,
    LLMProvider.XAI,
    LLMProvider.XAI_OAUTH,
)


@router.get("/workspaces/{handle}/llm-provider-integrations/providers")
async def list_integration_providers(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
) -> LLMProviderCapabilityListResponse:
    """List provider options available to create in this workspace."""
    if not member.has_permission(Permissions.LLM_INTEGRATIONS_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No LLM integration read permission.",
        )
    return LLMProviderCapabilityListResponse(
        items=[
            LLMProviderCapabilityResponse(
                provider=provider,
                display_name=_PROVIDER_DISPLAY_NAMES[provider],
                credential_type=PROVIDER_SECRET_TYPES[provider],
                experimental=provider == LLMProvider.XAI_OAUTH,
            )
            for provider in _BASE_AVAILABLE_PROVIDERS
        ]
    )


@router.post(
    "/workspaces/{handle}/llm-provider-integrations",
    status_code=status.HTTP_201_CREATED,
)
async def create_integration(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[LLMProviderIntegrationService, Depends()],
    catalog_sync_service: Annotated[IntegrationCatalogProjectionService, Depends()],
    background_tasks: BackgroundTasks,
    *,
    request_body: LLMProviderIntegrationCreateRequest,
) -> LLMProviderIntegrationResponse:
    """Create an LLM Provider Integration.

    Requires LLM integration write permission.
    """
    if not member.has_permission(Permissions.LLM_INTEGRATIONS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No LLM integration management permission.",
        )
    name = request_body.name or _PROVIDER_DISPLAY_NAMES.get(
        request_body.provider, request_body.provider.value
    )
    create_input = LLMProviderIntegrationCreateInput(
        workspace_id=member.workspace_id,
        provider=request_body.provider,
        name=name,
        secrets=request_body.secrets,
        config=request_body.config,
        enabled=request_body.enabled,
    )
    integration = await service.create(create_input)
    enqueue_initial_catalog_sync(
        background_tasks,
        service=catalog_sync_service,
        integration_id=integration.id,
        workspace_id=member.workspace_id,
        provider=integration.provider,
        name=integration.name,
        enabled=integration.enabled,
        trigger=IntegrationCatalogSyncTrigger.CREATE,
    )
    return LLMProviderIntegrationResponse.convert_from(integration)


@router.get("/workspaces/{handle}/llm-provider-integrations")
async def list_integrations(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[LLMProviderIntegrationService, Depends()],
) -> LLMProviderIntegrationListResponse:
    """List LLM Provider Integrations in a workspace.

    Requires LLM integration read permission.
    """
    if not member.has_permission(Permissions.LLM_INTEGRATIONS_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No LLM integration read permission.",
        )

    result = await service.list_by_workspace(member.workspace_id)
    return LLMProviderIntegrationListResponse(
        items=[LLMProviderIntegrationResponse.convert_from(i) for i in result.items]
    )


@router.get("/workspaces/{handle}/llm-provider-integrations/{integration_id}")
async def get_integration(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[LLMProviderIntegrationService, Depends()],
    *,
    integration_id: str,
) -> LLMProviderIntegrationResponse:
    """Get LLM Provider Integration details.

    Requires LLM integration read permission.
    """
    if not member.has_permission(Permissions.LLM_INTEGRATIONS_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No LLM integration read permission.",
        )

    result = await service.get_by_id(integration_id, workspace_id=member.workspace_id)
    match result:
        case Success(value):
            return LLMProviderIntegrationResponse.convert_from(value)
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="LLM Provider Integration not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get(
    "/workspaces/{handle}/llm-provider-integrations/{integration_id}/subscription-usage",
    response_model=SubscriptionUsageResponse,
)
async def get_subscription_usage(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[SubscriptionUsageService, Depends()],
    *,
    integration_id: str,
) -> SubscriptionUsageResponse:
    """Read live subscription usage for one LLM provider integration."""
    if not member.has_permission(Permissions.LLM_INTEGRATIONS_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No LLM integration read permission.",
        )

    result = await service.read(
        integration_id=integration_id,
        workspace_id=member.workspace_id,
        include_financial_details=member.has_permission(
            Permissions.LLM_INTEGRATIONS_WRITE
        ),
    )
    match result:
        case Success(value):
            return convert_subscription_usage_response(value)
        case Failure(error):
            match error:
                case SubscriptionUsageNotFound() | SubscriptionUsageNotInWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="LLM Provider Integration not found.",
                    )
                case SubscriptionUsageUnsupportedProvider():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            "Integration provider does not support subscription usage."
                        ),
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get(
    "/workspaces/{handle}/llm-provider-integrations/{integration_id}/catalog-entries"
)
async def list_integration_catalog_entries(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ModelCatalogReadService, Depends()],
    catalog_sync_service: Annotated[IntegrationCatalogProjectionService, Depends()],
    background_tasks: BackgroundTasks,
    *,
    integration_id: str,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> ModelCatalogEntryListResponse:
    """List stored model catalog entries for an integration.

    Requires LLM integration read permission.
    This endpoint reads only stored projections and never calls providers.
    """
    if not member.has_permission(Permissions.LLM_INTEGRATIONS_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="LLM integration read permission is required.",
        )
    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Limit must be between 1 and 100.",
        )
    if offset < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Offset must be greater than or equal to 0.",
        )

    result = await service.list_entries_by_integration(
        integration_id=integration_id,
        workspace_id=member.workspace_id,
        search=search,
        limit=limit,
        offset=offset,
    )
    match result:
        case Success(value):
            enqueue_stale_catalog_sync(
                background_tasks,
                service=catalog_sync_service,
                integration_id=integration_id,
                workspace_id=member.workspace_id,
                catalog_scope=value.catalog_scope,
                stale=value.stale,
            )
            return ModelCatalogEntryListResponse.convert_from(value)
        case Failure(error):
            match error:
                case CatalogNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="LLM model catalog was not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post(
    "/workspaces/{handle}/llm-provider-integrations/{integration_id}/catalog-sync"
)
async def sync_integration_catalog(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[IntegrationCatalogProjectionService, Depends()],
    *,
    integration_id: str,
) -> ModelCatalogSyncResponse:
    """Synchronize stored model catalog entries for an integration.

    Requires LLM integration write permission.
    """
    if not member.has_permission(Permissions.LLM_INTEGRATIONS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="LLM integration management permission is required.",
        )
    result = await service.sync_integration_catalog(
        integration_id=integration_id,
        workspace_id=member.workspace_id,
    )
    match result:
        case Success(value):
            return ModelCatalogSyncResponse.convert_from(value)
        case Failure(error):
            match error:
                case IntegrationCatalogSyncNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="LLM provider integration was not found.",
                    )
                case IntegrationCatalogSyncUnsupportedProvider():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            "Integration provider does not have a user catalog sync."
                        ),
                    )
                case IntegrationCatalogSyncAlreadyRunning():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Integration catalog sync is already running.",
                    )
                case IntegrationCatalogSyncSuperseded():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            "Integration catalog sync was superseded by a newer "
                            "attempt."
                        ),
                    )
                case IntegrationCatalogSyncThrottled(retry_at=retry_at):
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=(
                            "Integration catalog sync is throttled until "
                            f"{retry_at.isoformat()}."
                        ),
                        headers={
                            "Retry-After": format_datetime(
                                retry_at.astimezone(datetime.UTC), usegmt=True
                            )
                        },
                    )
                case (
                    IntegrationCatalogAutomaticRetryBlocked()
                    | IntegrationCatalogSyncNotStale()
                ):
                    raise RuntimeError("Explicit catalog sync was denied unexpectedly.")
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.patch("/workspaces/{handle}/llm-provider-integrations/{integration_id}")
async def update_integration(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[LLMProviderIntegrationService, Depends()],
    catalog_sync_service: Annotated[IntegrationCatalogProjectionService, Depends()],
    background_tasks: BackgroundTasks,
    *,
    integration_id: str,
    request_body: LLMProviderIntegrationUpdateRequest,
) -> LLMProviderIntegrationResponse:
    """Update an LLM Provider Integration.

    Requires LLM integration write permission.
    """
    if not member.has_permission(Permissions.LLM_INTEGRATIONS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No LLM integration management permission.",
        )

    result = await service.update_by_id(
        integration_id, request_body, workspace_id=member.workspace_id
    )
    match result:
        case Success(value):
            if value.catalog_sync_required:
                enqueue_initial_catalog_sync(
                    background_tasks,
                    service=catalog_sync_service,
                    integration_id=value.integration.id,
                    workspace_id=member.workspace_id,
                    provider=value.integration.provider,
                    name=value.integration.name,
                    enabled=value.integration.enabled,
                    trigger=IntegrationCatalogSyncTrigger.CONFIG_UPDATE,
                )
            return LLMProviderIntegrationResponse.convert_from(value.integration)
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="LLM Provider Integration not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.delete(
    "/workspaces/{handle}/llm-provider-integrations/{integration_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_integration(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[LLMProviderIntegrationService, Depends()],
    *,
    integration_id: str,
) -> None:
    """Delete an LLM Provider Integration.

    Requires LLM integration write permission.
    """
    if not member.has_permission(Permissions.LLM_INTEGRATIONS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No LLM integration management permission.",
        )

    result = await service.delete_by_id(
        integration_id, workspace_id=member.workspace_id
    )
    match result:
        case Success():
            return
        case Failure(error):
            match error:
                case NotFound() | NotBelongToWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="LLM Provider Integration not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


def enqueue_stale_catalog_sync(
    background_tasks: BackgroundTasks,
    *,
    service: IntegrationCatalogProjectionService,
    integration_id: str,
    workspace_id: str,
    catalog_scope: LLMCatalogScope,
    stale: bool,
) -> None:
    """Queue lazy refresh after returning a stale stored projection."""
    if catalog_scope != LLMCatalogScope.INTEGRATION or not stale:
        return
    background_tasks.add_task(
        _run_catalog_sync,
        service=service,
        integration_id=integration_id,
        workspace_id=workspace_id,
        trigger=IntegrationCatalogSyncTrigger.STALE_REFRESH,
    )


def enqueue_initial_catalog_sync(
    background_tasks: BackgroundTasks,
    *,
    service: IntegrationCatalogProjectionService,
    integration_id: str,
    workspace_id: str,
    provider: LLMProvider,
    name: str,
    enabled: bool,
    trigger: IntegrationCatalogSyncTrigger,
) -> None:
    """Queue best-effort sync after an integration lifecycle change."""
    if not enabled:
        return
    deterministic_variant = parse_deterministic_fixture_variant(name)
    if (
        deterministic_variant is None
        and provider not in INTEGRATION_SCOPED_CATALOG_PROVIDERS
    ):
        return
    background_tasks.add_task(
        _run_catalog_sync,
        service=service,
        integration_id=integration_id,
        workspace_id=workspace_id,
        trigger=trigger,
    )


async def _run_catalog_sync(
    *,
    service: IntegrationCatalogProjectionService,
    integration_id: str,
    workspace_id: str,
    trigger: IntegrationCatalogSyncTrigger,
) -> None:
    """Run best-effort catalog sync without affecting the initiating response."""
    try:
        await service.sync_integration_catalog(
            integration_id=integration_id,
            workspace_id=workspace_id,
            trigger=trigger,
        )
    except Exception:
        logger.exception(
            "Unexpected integration catalog initial sync failure.",
            extra={"integration_id": integration_id, "workspace_id": workspace_id},
        )


def mount(mounter: RouteMounter) -> None:
    """Mount LLM Provider Integration v1 routes."""
    mounter(
        router,
        prefix="/llm-provider-integration/v1",
        tag="LLM Provider Integration v1",
        description=dedent(
            """
            LLM Provider Integration API (Public)

            Workspace-scoped LLM provider integration CRUD endpoints.
            Credentials are not included in responses.
            """
        ),
    )
