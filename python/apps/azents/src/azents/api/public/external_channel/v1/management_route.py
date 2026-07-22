"""Authenticated External Channel management API."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from azents.core.auth.deps import (
    CurrentUser,
    WorkspaceMember,
    get_current_user,
    get_workspace_member,
)
from azents.core.enums import ExternalChannelTransport
from azents.repos.external_channel.management_data import (
    ManagedApprovalRequest,
    ManagedBinding,
    ManagedBlock,
    ManagedConnection,
    ManagedGrant,
)
from azents.services.external_channel.access import (
    ExternalChannelAccessDecisionError,
    ExternalChannelAccessRequestNotFound,
)
from azents.services.external_channel.data import (
    ExternalChannelConnectionStatusSnapshot,
    SlackConnectionCredentials,
)
from azents.services.external_channel.management import (
    ExternalChannelDecisionInput,
    ExternalChannelManagementConflict,
    ExternalChannelManagementNotFound,
    ExternalChannelManagementService,
    ManagedConnectionSetup,
    SlackManifestGuidance,
    slack_manifest_guidance,
)

router = APIRouter()


class SlackConnectionSetupRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    app_id: str = Field(min_length=1, max_length=255)
    transport: ExternalChannelTransport
    credentials: SlackConnectionCredentials


class SlackReconnectRequest(BaseModel):
    credentials: SlackConnectionCredentials


class TransportSwitchRequest(BaseModel):
    transport: ExternalChannelTransport


class ManagedConnectionListResponse(BaseModel):
    items: list[ManagedConnection]


class ManagedBindingListResponse(BaseModel):
    items: list[ManagedBinding]
    grants: list[ManagedGrant]


class ManagedAccessResponse(BaseModel):
    grants: list[ManagedGrant]
    blocks: list[ManagedBlock]


@router.get(
    "/workspaces/{handle}/agents/{agent_id}/external-channels/manifest",
)
async def get_manifest_guidance(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    agent_id: str,
    transport: Annotated[ExternalChannelTransport, Query()],
) -> SlackManifestGuidance:
    """Return minimum Slack App configuration after Agent access validation."""
    try:
        await service.list_connections(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            workspace_user_id=member.workspace_user_id,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    return slack_manifest_guidance(transport)


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
            )
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


@router.patch(
    "/workspaces/{handle}/agents/{agent_id}/external-channels/{connection_id}/transport"
)
async def switch_transport(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    agent_id: str,
    connection_id: str,
    request_body: TransportSwitchRequest,
) -> ManagedConnectionSetup:
    """Switch inbound transport without silently falling back."""
    try:
        return await service.switch_transport(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            workspace_user_id=member.workspace_user_id,
            connection_id=connection_id,
            transport=request_body.transport,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ExternalChannelManagementConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/external-channels/{connection_id}/reconnect"
)
async def reconnect_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ExternalChannelManagementService, Depends()],
    *,
    agent_id: str,
    connection_id: str,
    request_body: SlackReconnectRequest,
) -> ExternalChannelConnectionStatusSnapshot:
    """Replace encrypted credentials and immediately validate them."""
    try:
        return await service.reconnect(
            workspace_id=member.workspace_id,
            agent_id=agent_id,
            workspace_user_id=member.workspace_user_id,
            connection_id=connection_id,
            credentials=request_body.credentials,
        )
    except ExternalChannelManagementNotFound as error:
        raise _not_found() from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


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
