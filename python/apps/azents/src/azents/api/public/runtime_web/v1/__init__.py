"""Runtime Web v1 Public API."""

from datetime import UTC, datetime
from typing import Annotated, Any, NoReturn, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from azents.core.auth.deps import (
    CurrentUser,
    WorkspaceMember,
    get_current_user,
    get_workspace_member,
)
from azents.rdb.models.runtime_web import RuntimeWebActorKind
from azents.repos.runtime_web.repository import RuntimeWebRepositoryConflict
from azents.services.runtime_web.data import (
    RuntimeWebAccessDenied,
    RuntimeWebActor,
    RuntimeWebCapabilityUnavailable,
    RuntimeWebConfigurationUnavailable,
    RuntimeWebConflict,
    RuntimeWebError,
    RuntimeWebNotFound,
    RuntimeWebOperation,
    RuntimeWebQuotaExceeded,
)
from azents.services.runtime_web.gateway_auth import RuntimeWebGatewayAuthService
from azents.services.runtime_web.gateway_auth_deps import (
    get_runtime_web_gateway_auth_service,
)
from azents.services.runtime_web.service import (
    RuntimeWebService,
    get_runtime_web_service,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    RuntimeWebActionErrorResponse,
    RuntimeWebCreateRequest,
    RuntimeWebDeleteResponse,
    RuntimeWebExpectedRevisionRequest,
    RuntimeWebIdentityRevokeRequest,
    RuntimeWebIdentityRevokeResponse,
    RuntimeWebIdentitySecretResponse,
    RuntimeWebSeparateBoundRequest,
    RuntimeWebSeparateInitiateRequest,
    RuntimeWebSeparateInitiateResponse,
    RuntimeWebSeparateTicketResponse,
    RuntimeWebServiceListResponse,
    RuntimeWebServiceResponse,
    RuntimeWebTurnOnRequest,
    RuntimeWebUpdateRequest,
)

router = APIRouter()
RuntimeWebServiceId = Annotated[str, Path(min_length=32, max_length=32)]

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_403_FORBIDDEN: {
        "model": RuntimeWebActionErrorResponse,
        "description": "The caller cannot disclose or manage this Agent service.",
    },
    status.HTTP_404_NOT_FOUND: {
        "model": RuntimeWebActionErrorResponse,
        "description": "The service resource is unavailable or intentionally hidden.",
    },
    status.HTTP_409_CONFLICT: {
        "model": RuntimeWebActionErrorResponse,
        "description": (
            "The service state, Runtime capability, or installation changed."
        ),
    },
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": RuntimeWebActionErrorResponse,
        "description": "A logical Runtime Web service quota is exhausted.",
    },
}

_AUTH_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_409_CONFLICT: {
        "model": RuntimeWebActionErrorResponse,
        "description": "The authentication exchange or installation changed.",
    }
}


def _user_actor(member: WorkspaceMember) -> RuntimeWebActor:
    return RuntimeWebActor(
        kind=RuntimeWebActorKind.USER,
        actor_id=member.user_id,
        execution_id=member.session_id,
        call_id=None,
    )


def _current_user_actor(current_user: CurrentUser) -> RuntimeWebActor:
    return RuntimeWebActor(
        kind=RuntimeWebActorKind.USER,
        actor_id=current_user.user_id,
        execution_id=current_user.session_id,
        call_id=None,
    )


def _operation(operation_key: str) -> RuntimeWebOperation:
    return RuntimeWebOperation(operation_key=operation_key)


def _raise_runtime_web_error(error: RuntimeWebError) -> NoReturn:
    match error:
        case RuntimeWebNotFound():
            code = status.HTTP_404_NOT_FOUND
            detail = "not_found"
        case RuntimeWebAccessDenied():
            code = status.HTTP_403_FORBIDDEN
            detail = "access_denied"
        case RuntimeWebConflict():
            code = status.HTTP_409_CONFLICT
            detail = "conflict"
        case RuntimeWebQuotaExceeded(scope=scope):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"code": "quota_exceeded", "scope": scope},
            )
        case RuntimeWebConfigurationUnavailable():
            code = status.HTTP_409_CONFLICT
            detail = "configuration_unavailable"
        case RuntimeWebCapabilityUnavailable():
            code = status.HTTP_409_CONFLICT
            detail = "runtime_capability_unavailable"
        case _ as unreachable:
            assert_never(unreachable)
    raise HTTPException(status_code=code, detail={"code": detail, "scope": None})


def _raise_auth_conflict() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "conflict", "scope": None},
    )


@router.post(
    "/auth/shared-identity",
    response_model=RuntimeWebIdentitySecretResponse,
    responses=_AUTH_ERROR_RESPONSES,
)
async def issue_runtime_web_shared_identity(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[
        RuntimeWebGatewayAuthService,
        Depends(get_runtime_web_gateway_auth_service),
    ],
) -> RuntimeWebIdentitySecretResponse:
    """Mint one opaque Gateway identity for a trusted Main Web response."""
    try:
        issued = await service.issue_shared_identity(
            user_id=current_user.user_id,
            auth_session_id=current_user.session_id,
            now=datetime.now(UTC),
        )
    except RuntimeWebRepositoryConflict:
        _raise_auth_conflict()
    return RuntimeWebIdentitySecretResponse(
        secret=issued.secret,
        expires_at=issued.expires_at,
    )


@router.post(
    "/auth/revoke-identity",
    response_model=RuntimeWebIdentityRevokeResponse,
)
async def revoke_runtime_web_identity(
    request_body: RuntimeWebIdentityRevokeRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[
        RuntimeWebGatewayAuthService,
        Depends(get_runtime_web_gateway_auth_service),
    ],
) -> RuntimeWebIdentityRevokeResponse:
    """Revoke a Gateway identity during trusted logout."""
    return RuntimeWebIdentityRevokeResponse(
        revoked=await service.revoke(
            secret=request_body.secret,
            user_id=current_user.user_id,
            auth_session_id=current_user.session_id,
            now=datetime.now(UTC),
        )
    )


@router.post(
    "/auth/separate/initiate",
    response_model=RuntimeWebSeparateInitiateResponse,
    responses=_AUTH_ERROR_RESPONSES,
)
async def initiate_runtime_web_separate_identity(
    request_body: RuntimeWebSeparateInitiateRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[
        RuntimeWebGatewayAuthService,
        Depends(get_runtime_web_gateway_auth_service),
    ],
) -> RuntimeWebSeparateInitiateResponse:
    """Create one Main-origin binding without a URL-carried secret."""
    try:
        issued = await service.initiate_separate_domain(
            user_id=current_user.user_id,
            auth_session_id=current_user.session_id,
            service_id=request_body.service_id,
            now=datetime.now(UTC),
        )
    except RuntimeWebRepositoryConflict:
        _raise_auth_conflict()
    return RuntimeWebSeparateInitiateResponse(
        initiation_id=issued.binding.initiation_id,
        main_binding_secret=issued.main_binding_secret,
        expires_at=issued.binding.expires_at,
    )


@router.post(
    "/auth/separate/bound",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_AUTH_ERROR_RESPONSES,
)
async def mark_runtime_web_separate_identity_bound(
    request_body: RuntimeWebSeparateBoundRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[
        RuntimeWebGatewayAuthService,
        Depends(get_runtime_web_gateway_auth_service),
    ],
) -> None:
    """Record the exact broker callback under the current auth Session."""
    try:
        await service.mark_broker_bound(
            initiation_id=request_body.initiation_id,
            main_binding_secret=request_body.main_binding_secret,
            user_id=current_user.user_id,
            auth_session_id=current_user.session_id,
            now=datetime.now(UTC),
        )
    except RuntimeWebRepositoryConflict:
        _raise_auth_conflict()


@router.post(
    "/auth/separate/ticket",
    response_model=RuntimeWebSeparateTicketResponse,
    responses=_AUTH_ERROR_RESPONSES,
)
async def issue_runtime_web_separate_ticket(
    request_body: RuntimeWebSeparateBoundRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[
        RuntimeWebGatewayAuthService,
        Depends(get_runtime_web_gateway_auth_service),
    ],
) -> RuntimeWebSeparateTicketResponse:
    """Issue one thirty-second ticket after the broker callback."""
    try:
        issued = await service.issue_ticket(
            initiation_id=request_body.initiation_id,
            main_binding_secret=request_body.main_binding_secret,
            user_id=current_user.user_id,
            auth_session_id=current_user.session_id,
            now=datetime.now(UTC),
        )
    except RuntimeWebRepositoryConflict:
        _raise_auth_conflict()
    return RuntimeWebSeparateTicketResponse(
        ticket_secret=issued.ticket_secret,
        service_id=issued.service_id,
        expires_at=issued.expires_at,
    )


@router.get(
    "/workspaces/{handle}/agents/{agent_id}/services",
    response_model=RuntimeWebServiceListResponse,
    responses=_ERROR_RESPONSES,
)
async def list_runtime_web_services(
    agent_id: str,
    workspace_member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeWebService, Depends(get_runtime_web_service)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> RuntimeWebServiceListResponse:
    """List services shared by every Session of one Agent."""
    result = await service.list_services(
        workspace_id=workspace_member.workspace_id,
        agent_id=agent_id,
        user_id=workspace_member.user_id,
        workspace_user_id=workspace_member.workspace_user_id,
        role=workspace_member.role,
        offset=offset,
        limit=limit,
        actor=_user_actor(workspace_member),
    )
    match result:
        case Success(page):
            return RuntimeWebServiceListResponse.convert_from(page)
        case Failure(error):
            _raise_runtime_web_error(error)
        case _ as unreachable:
            assert_never(unreachable)


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/services",
    response_model=RuntimeWebServiceResponse,
    responses=_ERROR_RESPONSES,
)
async def create_runtime_web_service(
    agent_id: str,
    request_body: RuntimeWebCreateRequest,
    workspace_member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeWebService, Depends(get_runtime_web_service)],
) -> RuntimeWebServiceResponse:
    """Create one Agent-port service directly."""
    result = await service.create_service(
        workspace_id=workspace_member.workspace_id,
        agent_id=agent_id,
        user_id=workspace_member.user_id,
        workspace_user_id=workspace_member.workspace_user_id,
        role=workspace_member.role,
        port=request_body.port,
        label=request_body.label,
        selected_duration_seconds=request_body.selected_duration_seconds,
        turn_on=request_body.turn_on,
        actor=_user_actor(workspace_member),
        operation=_operation(request_body.operation_key),
    )
    match result:
        case Success(projection):
            return RuntimeWebServiceResponse.convert_from(projection)
        case Failure(error):
            _raise_runtime_web_error(error)
        case _ as unreachable:
            assert_never(unreachable)


@router.get(
    "/workspaces/{handle}/agents/{agent_id}/services/{service_id}",
    response_model=RuntimeWebServiceResponse,
    responses=_ERROR_RESPONSES,
)
async def get_runtime_web_service_projection(
    agent_id: str,
    service_id: RuntimeWebServiceId,
    workspace_member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeWebService, Depends(get_runtime_web_service)],
) -> RuntimeWebServiceResponse:
    """Get one exact Agent-owned service."""
    result = await service.get_service(
        workspace_id=workspace_member.workspace_id,
        agent_id=agent_id,
        service_id=service_id,
        user_id=workspace_member.user_id,
        workspace_user_id=workspace_member.workspace_user_id,
        role=workspace_member.role,
    )
    match result:
        case Success(projection):
            return RuntimeWebServiceResponse.convert_from(projection)
        case Failure(error):
            _raise_runtime_web_error(error)
        case _ as unreachable:
            assert_never(unreachable)


@router.patch(
    "/workspaces/{handle}/agents/{agent_id}/services/{service_id}",
    response_model=RuntimeWebServiceResponse,
    responses=_ERROR_RESPONSES,
)
async def update_runtime_web_service(
    agent_id: str,
    service_id: RuntimeWebServiceId,
    request_body: RuntimeWebUpdateRequest,
    workspace_member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeWebService, Depends(get_runtime_web_service)],
) -> RuntimeWebServiceResponse:
    """Update label or selected duration without changing expiration."""
    result = await service.update_service(
        workspace_id=workspace_member.workspace_id,
        agent_id=agent_id,
        service_id=service_id,
        user_id=workspace_member.user_id,
        workspace_user_id=workspace_member.workspace_user_id,
        role=workspace_member.role,
        expected_revision=request_body.expected_revision,
        label_present="label" in request_body.model_fields_set,
        label=request_body.label,
        selected_duration_seconds=request_body.selected_duration_seconds,
        actor=_user_actor(workspace_member),
        operation=_operation(request_body.operation_key),
    )
    match result:
        case Success(projection):
            return RuntimeWebServiceResponse.convert_from(projection)
        case Failure(error):
            _raise_runtime_web_error(error)
        case _ as unreachable:
            assert_never(unreachable)


async def _service_action(
    *,
    action: str,
    agent_id: str,
    service_id: str,
    request_body: RuntimeWebExpectedRevisionRequest,
    workspace_member: WorkspaceMember,
    service: RuntimeWebService,
) -> RuntimeWebServiceResponse:
    actor = _user_actor(workspace_member)
    operation = _operation(request_body.operation_key)
    if action == "on":
        assert isinstance(request_body, RuntimeWebTurnOnRequest)
        result = await service.turn_on(
            workspace_id=workspace_member.workspace_id,
            agent_id=agent_id,
            service_id=service_id,
            user_id=workspace_member.user_id,
            workspace_user_id=workspace_member.workspace_user_id,
            role=workspace_member.role,
            expected_revision=request_body.expected_revision,
            selected_duration_seconds=request_body.selected_duration_seconds,
            actor=actor,
            operation=operation,
        )
    elif action == "off":
        result = await service.turn_off(
            workspace_id=workspace_member.workspace_id,
            agent_id=agent_id,
            service_id=service_id,
            user_id=workspace_member.user_id,
            workspace_user_id=workspace_member.workspace_user_id,
            role=workspace_member.role,
            expected_revision=request_body.expected_revision,
            actor=actor,
            operation=operation,
        )
    else:
        result = await service.reset_expiration(
            workspace_id=workspace_member.workspace_id,
            agent_id=agent_id,
            service_id=service_id,
            user_id=workspace_member.user_id,
            workspace_user_id=workspace_member.workspace_user_id,
            role=workspace_member.role,
            expected_revision=request_body.expected_revision,
            actor=actor,
            operation=operation,
        )
    match result:
        case Success(projection):
            return RuntimeWebServiceResponse.convert_from(projection)
        case Failure(error):
            _raise_runtime_web_error(error)
        case _ as unreachable:
            assert_never(unreachable)


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/services/{service_id}/on",
    response_model=RuntimeWebServiceResponse,
    responses=_ERROR_RESPONSES,
)
async def turn_on_runtime_web_service(
    agent_id: str,
    service_id: RuntimeWebServiceId,
    request_body: RuntimeWebTurnOnRequest,
    workspace_member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeWebService, Depends(get_runtime_web_service)],
) -> RuntimeWebServiceResponse:
    """Turn one Off service On."""
    return await _service_action(
        action="on",
        agent_id=agent_id,
        service_id=service_id,
        request_body=request_body,
        workspace_member=workspace_member,
        service=service,
    )


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/services/{service_id}/off",
    response_model=RuntimeWebServiceResponse,
    responses=_ERROR_RESPONSES,
)
async def turn_off_runtime_web_service(
    agent_id: str,
    service_id: RuntimeWebServiceId,
    request_body: RuntimeWebExpectedRevisionRequest,
    workspace_member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeWebService, Depends(get_runtime_web_service)],
) -> RuntimeWebServiceResponse:
    """Turn one service Off without deleting it."""
    return await _service_action(
        action="off",
        agent_id=agent_id,
        service_id=service_id,
        request_body=request_body,
        workspace_member=workspace_member,
        service=service,
    )


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/services/{service_id}/reset",
    response_model=RuntimeWebServiceResponse,
    responses=_ERROR_RESPONSES,
)
async def reset_runtime_web_service_expiration(
    agent_id: str,
    service_id: RuntimeWebServiceId,
    request_body: RuntimeWebExpectedRevisionRequest,
    workspace_member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeWebService, Depends(get_runtime_web_service)],
) -> RuntimeWebServiceResponse:
    """Restart one On service exposure window."""
    return await _service_action(
        action="reset",
        agent_id=agent_id,
        service_id=service_id,
        request_body=request_body,
        workspace_member=workspace_member,
        service=service,
    )


@router.delete(
    "/workspaces/{handle}/agents/{agent_id}/services/{service_id}",
    response_model=RuntimeWebDeleteResponse,
    responses=_ERROR_RESPONSES,
)
async def delete_runtime_web_service(
    agent_id: str,
    service_id: RuntimeWebServiceId,
    request_body: RuntimeWebExpectedRevisionRequest,
    workspace_member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeWebService, Depends(get_runtime_web_service)],
) -> RuntimeWebDeleteResponse:
    """Delete one service and retire its public address."""
    result = await service.delete_service(
        workspace_id=workspace_member.workspace_id,
        agent_id=agent_id,
        service_id=service_id,
        user_id=workspace_member.user_id,
        workspace_user_id=workspace_member.workspace_user_id,
        role=workspace_member.role,
        expected_revision=request_body.expected_revision,
        actor=_user_actor(workspace_member),
        operation=_operation(request_body.operation_key),
    )
    match result:
        case Success(deleted):
            return RuntimeWebDeleteResponse(deleted=deleted)
        case Failure(error):
            _raise_runtime_web_error(error)
        case _ as unreachable:
            assert_never(unreachable)


@router.get(
    "/services/{service_id}",
    response_model=RuntimeWebServiceResponse,
    responses=_ERROR_RESPONSES,
)
async def get_runtime_web_service_by_id(
    service_id: RuntimeWebServiceId,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[RuntimeWebService, Depends(get_runtime_web_service)],
) -> RuntimeWebServiceResponse:
    """Get one service for the trusted Main Web activation surface."""
    result = await service.get_service_by_id_for_user(
        service_id=service_id,
        user_id=current_user.user_id,
    )
    match result:
        case Success(projection):
            return RuntimeWebServiceResponse.convert_from(projection)
        case Failure(error):
            _raise_runtime_web_error(error)
        case _ as unreachable:
            assert_never(unreachable)


@router.post(
    "/services/{service_id}/on",
    response_model=RuntimeWebServiceResponse,
    responses=_ERROR_RESPONSES,
)
async def turn_on_runtime_web_service_by_id(
    service_id: RuntimeWebServiceId,
    request_body: RuntimeWebTurnOnRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    service: Annotated[RuntimeWebService, Depends(get_runtime_web_service)],
) -> RuntimeWebServiceResponse:
    """Turn On one service from the trusted Main Web activation surface."""
    result = await service.turn_on_by_id_for_user(
        service_id=service_id,
        user_id=current_user.user_id,
        expected_revision=request_body.expected_revision,
        selected_duration_seconds=(
            request_body.selected_duration_seconds
            if request_body.selected_duration_seconds is not None
            else 3_600
        ),
        actor=_current_user_actor(current_user),
        operation=_operation(request_body.operation_key),
    )
    match result:
        case Success(projection):
            return RuntimeWebServiceResponse.convert_from(projection)
        case Failure(error):
            _raise_runtime_web_error(error)
        case _ as unreachable:
            assert_never(unreachable)


def mount(mounter: RouteMounter) -> None:
    """Mount Runtime Web routes."""
    mounter(
        router,
        prefix="/runtime-web/v1",
        tag="Runtime Web v1",
        description="Agent-scoped Runtime Web service management and authentication.",
    )
