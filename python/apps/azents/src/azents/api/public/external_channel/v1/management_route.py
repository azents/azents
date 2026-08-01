"""Authenticated External Channel management API."""

import datetime
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from azents.core.auth.deps import (
    CurrentUser,
    WorkspaceMember,
    get_current_user,
    get_workspace_member,
)
from azents.core.auth.permissions import Permission, Permissions
from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    ExternalChannelProvider,
    ExternalChannelResponseMode,
    ExternalChannelTransport,
)
from azents.repos.external_channel.data import (
    ExternalChannelMultiConnectionImpact,
    ExternalChannelMultiRouteImpact,
)
from azents.repos.external_channel.management_data import (
    ManagedApprovalRequest,
    ManagedBinding,
    ManagedBlock,
    ManagedChannelDefault,
    ManagedConnection,
    ManagedGrant,
    ManagedMultiConnection,
    ManagedMultiConnectionDisconnect,
    ManagedMultiRoute,
    ManagedSlackManagementHandoff,
)
from azents.services.external_channel.access import (
    ExternalChannelAccessDecisionError,
    ExternalChannelAccessRequestNotFound,
)
from azents.services.external_channel.connection import (
    ExternalChannelConnectionStateChanged,
)
from azents.services.external_channel.data import (
    DiscordConnectionConfiguration,
    DiscordConnectionCredentials,
    ExternalChannelConnectionStatusSnapshot,
    SlackConnectionCredentials,
)
from azents.services.external_channel.discord_api import (
    DiscordAPIConfigurationInvalid,
    DiscordAPICredentialsInvalid,
    DiscordAPIError,
    DiscordAPIUnavailable,
)
from azents.services.external_channel.management import (
    ExternalChannelAccessPolicyInput,
    ExternalChannelDecisionInput,
    ExternalChannelManagementGenerationChanged,
    ExternalChannelManagementNotFound,
    ExternalChannelManagementService,
    ExternalChannelResponseModeSetting,
    ManagedConnectionSetup,
    ManagedMultiConnectionSetup,
    SlackManifestGuidance,
    slack_manifest_guidance,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class SlackConnectionSetupRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    app_id: str = Field(min_length=1, max_length=255)
    transport: ExternalChannelTransport
    credentials: SlackConnectionCredentials


class DiscordConnectionSetupRequest(BaseModel):
    """Secret-bearing Discord App setup input."""

    model_config = ConfigDict(str_strip_whitespace=True)

    app_id: str = Field(min_length=1, max_length=255)
    configuration: DiscordConnectionConfiguration
    credentials: DiscordConnectionCredentials


class ManagedConnectionListResponse(BaseModel):
    items: list[ManagedConnection]
    associated_multi_apps: list[ManagedMultiConnection]
    default_response_mode: ExternalChannelResponseMode


class ManagedBindingListResponse(BaseModel):
    items: list[ManagedBinding]
    grants: list[ManagedGrant]


class ManagedAccessResponse(BaseModel):
    grants: list[ManagedGrant]
    blocks: list[ManagedBlock]


class ManagedMultiConnectionListResponse(BaseModel):
    items: list[ManagedMultiConnection]


class ManagedMultiRouteListResponse(BaseModel):
    items: list[ManagedMultiRoute]


class ManagedChannelDefaultListResponse(BaseModel):
    items: list[ManagedChannelDefault]


class MultiRouteCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    agent_id: str = Field(min_length=1, max_length=32)


class GenerationFenceRequest(BaseModel):
    expected_generation: datetime.datetime


class MultiChannelDefaultRequest(GenerationFenceRequest):
    model_config = ConfigDict(str_strip_whitespace=True)

    route_id: str = Field(min_length=1, max_length=32)


class ConnectionAccessPolicyRequest(ExternalChannelAccessPolicyInput):
    """Dedicated External Channel ingress policy request."""


class ResponseModeRequest(ExternalChannelResponseModeSetting):
    """Required full-value response-mode request."""


@router.get("/workspaces/{handle}/external-channels/multi")
async def list_multi_connections(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ManagedMultiConnectionListResponse:
    """List Workspace-owned Multi Apps across providers in one stable page."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_READ)
    return ManagedMultiConnectionListResponse(
        items=await service.list_multi_connections(
            workspace_id=member.workspace_id,
            provider=None,
            offset=offset,
            limit=limit,
        )
    )


@router.get("/workspaces/{handle}/external-channels/slack/multi")
async def list_multi_slack_connections(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ManagedMultiConnectionListResponse:
    """List Workspace-owned Slack Multi Apps."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_READ)
    return ManagedMultiConnectionListResponse(
        items=await service.list_multi_connections(
            workspace_id=member.workspace_id,
            provider=ExternalChannelProvider.SLACK,
            offset=offset,
            limit=limit,
        )
    )


@router.get("/workspaces/{handle}/external-channels/discord/multi")
async def list_multi_discord_connections(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ManagedMultiConnectionListResponse:
    """List Workspace-owned Discord Multi Apps."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_READ)
    return ManagedMultiConnectionListResponse(
        items=await service.list_multi_connections(
            workspace_id=member.workspace_id,
            provider=ExternalChannelProvider.DISCORD,
            offset=offset,
            limit=limit,
        )
    )


@router.post(
    "/workspaces/{handle}/external-channels/slack/multi",
    status_code=status.HTTP_201_CREATED,
)
async def setup_multi_slack_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    config: Annotated[Config, Depends(get_config)],
    *,
    request_body: SlackConnectionSetupRequest,
) -> ManagedMultiConnectionSetup:
    """Create a zero-Agent-capable Workspace Slack Multi App."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_WRITE)
    _require_multi_app_enabled(config)
    try:
        return await service.setup_multi_slack(
            workspace_id=member.workspace_id,
            app_id=request_body.app_id,
            transport=request_body.transport,
            credentials=request_body.credentials,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post(
    "/workspaces/{handle}/external-channels/discord/multi",
    status_code=status.HTTP_201_CREATED,
)
async def setup_multi_discord_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    config: Annotated[Config, Depends(get_config)],
    *,
    request_body: DiscordConnectionSetupRequest,
) -> ManagedMultiConnectionSetup:
    """Create a zero-Agent-capable configuring Workspace Discord Multi App."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_WRITE)
    _require_multi_app_enabled(config)
    try:
        return await service.setup_multi_discord(
            workspace_id=member.workspace_id,
            app_id=request_body.app_id,
            configuration=request_body.configuration,
            credentials=request_body.credentials,
        )
    except DiscordAPIError as error:
        raise _discord_activation_error(
            error,
            operation="setup_multi",
            connection_id=None,
        ) from error
    except ValueError as error:
        raise _discord_activation_error(
            error,
            operation="setup_multi",
            connection_id=None,
        ) from error


@router.get("/workspaces/{handle}/external-channels/slack/multi/{connection_id}")
async def get_multi_slack_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
) -> ManagedMultiConnection:
    """Load one redacted Workspace Slack Multi App."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_READ)
    try:
        return await service.get_multi_connection(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.SLACK,
            include_disconnected=True,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.get("/workspaces/{handle}/external-channels/slack/multi/{connection_id}/impact")
async def get_multi_slack_connection_impact(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
) -> ExternalChannelMultiConnectionImpact:
    """Preview sanitized impact before disconnecting one whole Multi App."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_READ)
    try:
        return await service.get_multi_connection_impact(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.SLACK,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.put("/workspaces/{handle}/external-channels/slack/multi/{connection_id}")
async def update_multi_slack_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
    request_body: SlackConnectionSetupRequest,
) -> ExternalChannelConnectionStatusSnapshot:
    """Replace complete Slack Multi App setup and immediately validate it."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_WRITE)
    try:
        return await service.update_multi_slack(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            app_id=request_body.app_id,
            transport=request_body.transport,
            credentials=request_body.credentials,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ExternalChannelConnectionStateChanged as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.put("/workspaces/{handle}/external-channels/discord/multi/{connection_id}")
async def update_multi_discord_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
    request_body: DiscordConnectionSetupRequest,
) -> ExternalChannelConnectionStatusSnapshot:
    """Replace a Discord Multi App and reactivate its callback authority."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_WRITE)
    try:
        return await service.update_multi_discord(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            app_id=request_body.app_id,
            configuration=request_body.configuration,
            credentials=request_body.credentials,
        )
    except DiscordAPIError as error:
        raise _discord_activation_error(
            error,
            operation="update_multi",
            connection_id=connection_id,
        ) from error
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ExternalChannelConnectionStateChanged as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise _discord_activation_error(
            error,
            operation="update_multi",
            connection_id=connection_id,
        ) from error


@router.post(
    "/workspaces/{handle}/external-channels/slack/multi/{connection_id}/validate"
)
async def validate_multi_slack_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
) -> ExternalChannelConnectionStatusSnapshot:
    """Validate one Workspace Multi App."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_WRITE)
    try:
        return await service.validate_multi_connection(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.SLACK,
        )
    except DiscordAPIError as error:
        raise _discord_activation_error(
            error,
            operation="validate_multi",
            connection_id=connection_id,
        ) from error
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ExternalChannelConnectionStateChanged as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise _discord_activation_error(
            error,
            operation="validate_multi",
            connection_id=connection_id,
        ) from error


@router.delete("/workspaces/{handle}/external-channels/slack/multi/{connection_id}")
async def disconnect_multi_slack_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
    request_body: GenerationFenceRequest,
) -> ManagedMultiConnectionDisconnect:
    """Generation-fence terminal disconnect of one Workspace Slack Multi App."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_WRITE)
    try:
        return await service.disconnect_multi_connection(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.SLACK,
            expected_generation=request_body.expected_generation,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ExternalChannelManagementGenerationChanged as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/workspaces/{handle}/external-channels/slack/multi/{connection_id}/agents")
async def list_multi_slack_routes(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ManagedMultiRouteListResponse:
    """List a paged Multi App Agent catalog, including removed routes."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_READ)
    try:
        return ManagedMultiRouteListResponse(
            items=await service.list_multi_routes(
                workspace_id=member.workspace_id,
                connection_id=connection_id,
                provider=ExternalChannelProvider.SLACK,
                offset=offset,
                limit=limit,
            )
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.post(
    "/workspaces/{handle}/external-channels/slack/multi/{connection_id}/agents",
    status_code=status.HTTP_201_CREATED,
)
async def add_multi_slack_route(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    config: Annotated[Config, Depends(get_config)],
    *,
    connection_id: str,
    request_body: MultiRouteCreateRequest,
) -> ManagedMultiRoute:
    """Add one active Workspace Agent to a Slack Multi App catalog."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_WRITE)
    _require_multi_app_enabled(config)
    try:
        return await service.add_multi_route(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.SLACK,
            agent_id=request_body.agent_id,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get(
    "/workspaces/{handle}/external-channels/slack/multi/{connection_id}/"
    "agents/{route_id}/impact"
)
async def get_multi_slack_route_impact(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
    route_id: str,
) -> ExternalChannelMultiRouteImpact:
    """Preview sanitized impact before removing one Multi App Agent route."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_READ)
    try:
        return await service.get_multi_route_impact(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.SLACK,
            route_id=route_id,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.delete(
    "/workspaces/{handle}/external-channels/slack/multi/{connection_id}/"
    "agents/{route_id}"
)
async def remove_multi_slack_route(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
    route_id: str,
    request_body: GenerationFenceRequest,
) -> ExternalChannelMultiRouteImpact:
    """Generation-fence destructive removal of one Multi App Agent route."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_WRITE)
    try:
        return await service.remove_multi_route(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.SLACK,
            route_id=route_id,
            user_id=member.user_id,
            expected_generation=request_body.expected_generation,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ExternalChannelManagementGenerationChanged as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post(
    "/workspaces/{handle}/external-channels/slack/multi/{connection_id}/"
    "agents/{route_id}/reenable"
)
async def reenable_multi_slack_route(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    config: Annotated[Config, Depends(get_config)],
    *,
    connection_id: str,
    route_id: str,
) -> ManagedMultiRoute:
    """Re-enable a previously removed Multi App Agent route."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_WRITE)
    _require_multi_app_enabled(config)
    try:
        return await service.reenable_multi_route(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.SLACK,
            route_id=route_id,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.get(
    "/workspaces/{handle}/external-channels/slack/multi/{connection_id}/"
    "channel-defaults"
)
async def list_multi_slack_channel_defaults(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ManagedChannelDefaultListResponse:
    """List paged Multi App channel-default history."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_READ)
    try:
        return ManagedChannelDefaultListResponse(
            items=await service.list_multi_channel_defaults(
                workspace_id=member.workspace_id,
                connection_id=connection_id,
                provider=ExternalChannelProvider.SLACK,
                offset=offset,
                limit=limit,
            )
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.put(
    "/workspaces/{handle}/external-channels/slack/multi/{connection_id}/"
    "channel-defaults/{provider_channel_id}"
)
async def replace_multi_slack_channel_default(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
    provider_channel_id: str,
    request_body: MultiChannelDefaultRequest,
) -> ManagedChannelDefault:
    """Generation-fence replacement of one Multi App channel default."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_WRITE)
    try:
        return await service.replace_multi_channel_default(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.SLACK,
            provider_channel_id=provider_channel_id,
            route_id=request_body.route_id,
            user_id=member.user_id,
            expected_generation=request_body.expected_generation,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ExternalChannelManagementGenerationChanged as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.delete(
    "/workspaces/{handle}/external-channels/slack/multi/{connection_id}/"
    "channel-defaults/{provider_channel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def clear_multi_slack_channel_default(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
    provider_channel_id: str,
    request_body: GenerationFenceRequest,
) -> None:
    """Generation-fence clearing one active Multi App channel default."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_WRITE)
    try:
        await service.clear_multi_channel_default(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.SLACK,
            provider_channel_id=provider_channel_id,
            expected_generation=request_body.expected_generation,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ExternalChannelManagementGenerationChanged as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/workspaces/{handle}/external-channels/discord/multi/{connection_id}")
async def get_multi_discord_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
) -> ManagedMultiConnection:
    """Load one redacted Workspace Discord Multi App."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_READ)
    try:
        return await service.get_multi_connection(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.DISCORD,
            include_disconnected=True,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.get(
    "/workspaces/{handle}/external-channels/discord/multi/{connection_id}/impact"
)
async def get_multi_discord_connection_impact(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
) -> ExternalChannelMultiConnectionImpact:
    """Preview sanitized impact before disconnecting one whole Multi App."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_READ)
    try:
        return await service.get_multi_connection_impact(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.DISCORD,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.post(
    "/workspaces/{handle}/external-channels/discord/multi/{connection_id}/validate"
)
async def validate_multi_discord_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
) -> ExternalChannelConnectionStatusSnapshot:
    """Validate one Workspace Multi App."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_WRITE)
    try:
        return await service.validate_multi_connection(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.DISCORD,
        )
    except DiscordAPIError as error:
        raise _discord_activation_error(
            error,
            operation="validate_multi",
            connection_id=connection_id,
        ) from error
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ExternalChannelConnectionStateChanged as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise _discord_activation_error(
            error,
            operation="validate_multi",
            connection_id=connection_id,
        ) from error


@router.delete("/workspaces/{handle}/external-channels/discord/multi/{connection_id}")
async def disconnect_multi_discord_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
    request_body: GenerationFenceRequest,
) -> ManagedMultiConnectionDisconnect:
    """Generation-fence terminal disconnect of one Workspace Discord Multi App."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_WRITE)
    try:
        return await service.disconnect_multi_connection(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.DISCORD,
            expected_generation=request_body.expected_generation,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ExternalChannelManagementGenerationChanged as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get(
    "/workspaces/{handle}/external-channels/discord/multi/{connection_id}/agents"
)
async def list_multi_discord_routes(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ManagedMultiRouteListResponse:
    """List a paged Multi App Agent catalog, including removed routes."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_READ)
    try:
        return ManagedMultiRouteListResponse(
            items=await service.list_multi_routes(
                workspace_id=member.workspace_id,
                connection_id=connection_id,
                provider=ExternalChannelProvider.DISCORD,
                offset=offset,
                limit=limit,
            )
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.post(
    "/workspaces/{handle}/external-channels/discord/multi/{connection_id}/agents",
    status_code=status.HTTP_201_CREATED,
)
async def add_multi_discord_route(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
    request_body: MultiRouteCreateRequest,
) -> ManagedMultiRoute:
    """Add one active Workspace Agent to a Discord Multi App catalog."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_WRITE)
    try:
        return await service.add_multi_route(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.DISCORD,
            agent_id=request_body.agent_id,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get(
    "/workspaces/{handle}/external-channels/discord/multi/{connection_id}/"
    "agents/{route_id}/impact"
)
async def get_multi_discord_route_impact(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
    route_id: str,
) -> ExternalChannelMultiRouteImpact:
    """Preview sanitized impact before removing one Multi App Agent route."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_READ)
    try:
        return await service.get_multi_route_impact(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.DISCORD,
            route_id=route_id,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.delete(
    "/workspaces/{handle}/external-channels/discord/multi/{connection_id}/"
    "agents/{route_id}"
)
async def remove_multi_discord_route(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
    route_id: str,
    request_body: GenerationFenceRequest,
) -> ExternalChannelMultiRouteImpact:
    """Generation-fence destructive removal of one Multi App Agent route."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_WRITE)
    try:
        return await service.remove_multi_route(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.DISCORD,
            route_id=route_id,
            user_id=member.user_id,
            expected_generation=request_body.expected_generation,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ExternalChannelManagementGenerationChanged as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post(
    "/workspaces/{handle}/external-channels/discord/multi/{connection_id}/"
    "agents/{route_id}/reenable"
)
async def reenable_multi_discord_route(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
    route_id: str,
) -> ManagedMultiRoute:
    """Re-enable a previously removed Multi App Agent route."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_WRITE)
    try:
        return await service.reenable_multi_route(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.DISCORD,
            route_id=route_id,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.get(
    "/workspaces/{handle}/external-channels/discord/multi/{connection_id}/"
    "channel-defaults"
)
async def list_multi_discord_channel_defaults(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ManagedChannelDefaultListResponse:
    """List paged Multi App channel-default history."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_READ)
    try:
        return ManagedChannelDefaultListResponse(
            items=await service.list_multi_channel_defaults(
                workspace_id=member.workspace_id,
                connection_id=connection_id,
                provider=ExternalChannelProvider.DISCORD,
                offset=offset,
                limit=limit,
            )
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.put(
    "/workspaces/{handle}/external-channels/discord/multi/{connection_id}/"
    "channel-defaults/{provider_channel_id}"
)
async def replace_multi_discord_channel_default(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
    provider_channel_id: str,
    request_body: MultiChannelDefaultRequest,
) -> ManagedChannelDefault:
    """Generation-fence replacement of one Multi App channel default."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_WRITE)
    try:
        return await service.replace_multi_channel_default(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.DISCORD,
            provider_channel_id=provider_channel_id,
            route_id=request_body.route_id,
            user_id=member.user_id,
            expected_generation=request_body.expected_generation,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ExternalChannelManagementGenerationChanged as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.delete(
    "/workspaces/{handle}/external-channels/discord/multi/{connection_id}/"
    "channel-defaults/{provider_channel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def clear_multi_discord_channel_default(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    connection_id: str,
    provider_channel_id: str,
    request_body: GenerationFenceRequest,
) -> None:
    """Generation-fence clearing one active Multi App channel default."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_WRITE)
    try:
        await service.clear_multi_channel_default(
            workspace_id=member.workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.DISCORD,
            provider_channel_id=provider_channel_id,
            expected_generation=request_body.expected_generation,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ExternalChannelManagementGenerationChanged as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get(
    "/workspaces/{handle}/external-channels/slack/multi/management-handoffs/"
    "{interaction_id}"
)
async def load_multi_slack_management_handoff(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    interaction_id: str,
) -> ManagedSlackManagementHandoff:
    """Load opaque Slack management state after authenticated Workspace recheck."""
    _require_workspace_permission(member, Permissions.EXTERNAL_CHANNELS_WRITE)
    try:
        return await service.load_multi_management_handoff(
            workspace_id=member.workspace_id,
            interaction_id=interaction_id,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.get(
    "/workspaces/{handle}/agents/{agent_id}/external-channels/manifest",
)
async def get_manifest_guidance(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    config: Annotated[Config, Depends(get_config)],
    *,
    agent_id: str,
    transport: Annotated[ExternalChannelTransport, Query()],
    app_name: Annotated[str, Query(min_length=1, max_length=80)] = "Azents Agent",
) -> SlackManifestGuidance:
    """Return copy-ready Slack App configuration after Agent access validation."""
    try:
        await service.list_connections(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            workspace_user_id=member.workspace_user_id,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    callback_url = config.external_channel_slack_callback_url
    if not callback_url:
        callback_url = f"{config.api_url.rstrip('/')}/external-channel/v1/slack/events"
    return slack_manifest_guidance(
        transport,
        callback_url=callback_url,
        app_name=app_name,
    )


@router.get("/workspaces/{handle}/agents/{agent_id}/external-channels")
async def list_connections(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    agent_id: str,
) -> ManagedConnectionListResponse:
    """List provider-neutral connections and routes for one Agent."""
    try:
        return ManagedConnectionListResponse(
            items=await service.list_connections(
                workspace_id=member.workspace_id,
                agent_id=agent_id,
                workspace_user_id=member.workspace_user_id,
            ),
            associated_multi_apps=await service.list_agent_multi_connections(
                workspace_id=member.workspace_id,
                agent_id=agent_id,
                workspace_user_id=member.workspace_user_id,
            ),
            default_response_mode=(
                await service.get_default_response_mode(
                    workspace_id=member.workspace_id,
                    agent_id=agent_id,
                    workspace_user_id=member.workspace_user_id,
                )
            ).response_mode,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.put(
    "/workspaces/{handle}/agents/{agent_id}/external-channels/default-response-mode"
)
async def update_default_response_mode(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    agent_id: str,
    request_body: ResponseModeRequest,
) -> ExternalChannelResponseModeSetting:
    """Replace the default copied to newly connected conversations."""
    try:
        return await service.update_default_response_mode(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            workspace_user_id=member.workspace_user_id,
            setting=request_body,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/external-channels/slack",
    status_code=status.HTTP_201_CREATED,
)
async def setup_slack_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    agent_id: str,
    request_body: SlackConnectionSetupRequest,
) -> ManagedConnectionSetup:
    """Create a dedicated Slack App connection and active Agent route."""
    try:
        return await service.setup_slack(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            workspace_user_id=member.workspace_user_id,
            app_id=request_body.app_id,
            transport=request_body.transport,
            credentials=request_body.credentials,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/external-channels/discord",
    status_code=status.HTTP_201_CREATED,
)
async def setup_discord_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    agent_id: str,
    request_body: DiscordConnectionSetupRequest,
) -> ManagedConnectionSetup:
    """Create a configuring dedicated Discord App and its sole Agent route."""
    try:
        return await service.setup_discord(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            workspace_user_id=member.workspace_user_id,
            app_id=request_body.app_id,
            configuration=request_body.configuration,
            credentials=request_body.credentials,
        )
    except DiscordAPIError as error:
        raise _discord_activation_error(
            error,
            operation="setup_dedicated",
            connection_id=None,
        ) from error
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ValueError as error:
        raise _discord_activation_error(
            error,
            operation="setup_dedicated",
            connection_id=None,
        ) from error


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/external-channels/{connection_id}/validate"
)
async def validate_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    agent_id: str,
    connection_id: str,
) -> ExternalChannelConnectionStatusSnapshot:
    """Validate credentials and activate or update sanitized connection health."""
    try:
        return await service.validate_connection(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            workspace_user_id=member.workspace_user_id,
            connection_id=connection_id,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ExternalChannelConnectionStateChanged as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    except DiscordAPIError as error:
        raise _discord_activation_error(
            error,
            operation="validate_dedicated",
            connection_id=connection_id,
        ) from error
    except ValueError as error:
        raise _discord_activation_error(
            error,
            operation="validate_dedicated",
            connection_id=connection_id,
        ) from error


@router.put(
    "/workspaces/{handle}/agents/{agent_id}/external-channels/{connection_id}/slack"
)
async def update_slack_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    agent_id: str,
    connection_id: str,
    request_body: SlackConnectionSetupRequest,
) -> ExternalChannelConnectionStatusSnapshot:
    """Replace the complete Slack setup and immediately validate it."""
    try:
        return await service.update_slack(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            workspace_user_id=member.workspace_user_id,
            connection_id=connection_id,
            app_id=request_body.app_id,
            transport=request_body.transport,
            credentials=request_body.credentials,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ExternalChannelConnectionStateChanged as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.put(
    "/workspaces/{handle}/agents/{agent_id}/external-channels/{connection_id}/discord"
)
async def update_discord_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    agent_id: str,
    connection_id: str,
    request_body: DiscordConnectionSetupRequest,
) -> ExternalChannelConnectionStatusSnapshot:
    """Replace a dedicated Discord App and reactivate callback authority."""
    try:
        return await service.update_discord(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            workspace_user_id=member.workspace_user_id,
            connection_id=connection_id,
            app_id=request_body.app_id,
            configuration=request_body.configuration,
            credentials=request_body.credentials,
        )
    except DiscordAPIError as error:
        raise _discord_activation_error(
            error,
            operation="update_dedicated",
            connection_id=connection_id,
        ) from error
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ExternalChannelConnectionStateChanged as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    except ValueError as error:
        raise _discord_activation_error(
            error,
            operation="update_dedicated",
            connection_id=connection_id,
        ) from error


@router.delete(
    "/workspaces/{handle}/agents/{agent_id}/external-channels/{connection_id}"
)
async def disconnect_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    agent_id: str,
    connection_id: str,
) -> ManagedConnection:
    """Terminally disconnect a connection after one-attempt progress cleanup."""
    try:
        return await service.disconnect_connection(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            workspace_user_id=member.workspace_user_id,
            connection_id=connection_id,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.put(
    "/workspaces/{handle}/agents/{agent_id}/external-channels/{connection_id}/access-policy"
)
async def update_connection_access_policy(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    agent_id: str,
    connection_id: str,
    request_body: ConnectionAccessPolicyRequest,
) -> ManagedConnection:
    """Update open human access and external bot-message admission."""
    try:
        return await service.update_connection_access_policy(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            workspace_user_id=member.workspace_user_id,
            connection_id=connection_id,
            policy=request_body,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.get("/workspaces/{handle}/agents/{agent_id}/external-channel-access")
async def list_agent_access(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    agent_id: str,
) -> ManagedAccessResponse:
    """List Agent grants and blocks without provider-native secret data."""
    try:
        grants, blocks = await service.list_agent_access(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            workspace_user_id=member.workspace_user_id,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    return ManagedAccessResponse(grants=grants, blocks=blocks)


@router.delete(
    "/workspaces/{handle}/agents/{agent_id}/external-channel-access/grants/{grant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_access_grant(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    agent_id: str,
    grant_id: str,
) -> None:
    """Revoke one Agent- or Session-scoped external participant grant."""
    try:
        await service.revoke_grant(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            workspace_user_id=member.workspace_user_id,
            user_id=member.user_id,
            grant_id=grant_id,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.delete(
    "/workspaces/{handle}/agents/{agent_id}/external-channel-access/blocks/{block_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_access_block(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    agent_id: str,
    block_id: str,
) -> None:
    """Remove one Agent-level external participant block."""
    try:
        await service.remove_block(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            workspace_user_id=member.workspace_user_id,
            user_id=member.user_id,
            block_id=block_id,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.get(
    "/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/external-channels"
)
async def list_session_channels(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    agent_id: str,
    session_id: str,
) -> ManagedBindingListResponse:
    """List bindings, Channel Work, delivery outcomes, and Session grants."""
    return ManagedBindingListResponse(
        items=await service.list_bindings(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            agent_session_id=session_id,
        ),
        grants=await service.list_session_grants(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            workspace_user_id=member.workspace_user_id,
            agent_session_id=session_id,
        ),
    )


@router.delete(
    "/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/external-channels/{binding_id}"
)
async def disconnect_session_channel(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    agent_id: str,
    session_id: str,
    binding_id: str,
) -> ManagedBindingListResponse:
    """Terminally disconnect one binding and retain its history."""
    try:
        items = await service.disconnect_binding(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            workspace_user_id=member.workspace_user_id,
            agent_session_id=session_id,
            binding_id=binding_id,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    return ManagedBindingListResponse(
        items=items,
        grants=await service.list_session_grants(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            workspace_user_id=member.workspace_user_id,
            agent_session_id=session_id,
        ),
    )


@router.put(
    "/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/"
    "external-channels/{binding_id}/response-mode"
)
async def update_session_channel_response_mode(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    agent_id: str,
    session_id: str,
    binding_id: str,
    request_body: ResponseModeRequest,
) -> ManagedBinding:
    """Replace one connected conversation binding's response mode."""
    try:
        return await service.update_binding_response_mode(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            workspace_user_id=member.workspace_user_id,
            agent_session_id=session_id,
            binding_id=binding_id,
            setting=request_body,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error


@router.get("/approval-requests/{access_request_id}")
async def get_approval_request(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    access_request_id: str,
) -> ManagedApprovalRequest:
    """Load one opaque authenticated approval request."""
    try:
        return await service.get_approval(
            access_request_id=access_request_id,
            user_id=current_user.user_id,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found("Approval request not found.") from error


@router.post("/approval-requests/{access_request_id}/decision")
async def decide_approval_request(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    access_request_id: str,
    request_body: ExternalChannelDecisionInput,
) -> ManagedApprovalRequest:
    """Apply one idempotent Allow Session, Allow Agent, Deny, or Block decision."""
    try:
        return await service.decide_approval(
            access_request_id=access_request_id,
            user_id=current_user.user_id,
            decision=request_body,
        )
    except (
        ExternalChannelManagementNotFound,
        ExternalChannelAccessRequestNotFound,
    ) as error:
        raise _not_found("Approval request not found.") from error
    except ExternalChannelAccessDecisionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


def _not_found(detail: str = "External Channel resource not found.") -> HTTPException:
    return HTTPException(status_code=404, detail=detail)


def _require_workspace_permission(
    member: WorkspaceMember,
    permission: Permission,
) -> None:
    """Enforce Workspace-owned Multi App management authority."""
    if not member.has_permission(permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No External Channel management permission.",
        )


def _require_multi_app_enabled(config: Config) -> None:
    """Reject new Multi data until operators complete mode-aware rollout."""
    if not config.external_channel_multi_app_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=("Multi App creation is not enabled for this deployment."),
        )


def _discord_activation_error(
    error: DiscordAPIError | ValueError,
    *,
    operation: str,
    connection_id: str | None,
) -> HTTPException:
    """Log a sanitized Discord setup failure and return a safe client error."""
    failure_stage, failure_code = _discord_activation_diagnostic(error)
    logger.error(
        "Discord External Channel activation failed",
        extra={
            "operation": operation,
            "connection_id": connection_id,
            "failure_stage": failure_stage,
            "failure_code": failure_code,
            "error_type": type(error).__name__,
        },
    )
    if isinstance(error, DiscordAPICredentialsInvalid):
        detail = {
            "code": "discord_credentials_invalid",
            "message": "Discord rejected the Bot Token.",
            "action_hint": "Replace the Bot Token and try again.",
        }
    elif isinstance(error, DiscordAPIConfigurationInvalid):
        detail = {
            "code": "discord_callback_configuration_invalid",
            "message": "Discord rejected the interaction endpoint.",
            "action_hint": (
                "Check the Application configuration and public callback URL, "
                "then try again."
            ),
        }
    elif isinstance(error, DiscordAPIUnavailable):
        detail = {
            "code": "discord_api_unavailable",
            "message": "Discord is temporarily unavailable.",
            "action_hint": "Try again later.",
        }
    else:
        detail = {
            "code": "discord_configuration_invalid",
            "message": "Discord connection configuration is invalid.",
            "action_hint": "Check the App settings and try again.",
        }
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _discord_activation_diagnostic(
    error: DiscordAPIError | ValueError,
) -> tuple[str, str]:
    """Return stable diagnostic fields without serializing exception data."""
    if isinstance(error, DiscordAPICredentialsInvalid):
        return "provider_authentication", "credentials_invalid"
    if isinstance(error, DiscordAPIConfigurationInvalid):
        return "provider_callback", "callback_configuration_invalid"
    if isinstance(error, DiscordAPIUnavailable):
        return "provider_api", "api_unavailable"
    return "configuration", "configuration_invalid"
