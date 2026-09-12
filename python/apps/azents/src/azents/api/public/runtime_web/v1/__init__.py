"""Runtime Web service control v1 Public API."""

from textwrap import dedent
from typing import Annotated, Any, NoReturn, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.rdb.models.runtime_web import RuntimeWebRequesterKind
from azents.services.runtime_web.data import (
    RuntimeWebAccessDenied,
    RuntimeWebActor,
    RuntimeWebConfigurationUnavailable,
    RuntimeWebConflict,
    RuntimeWebError,
    RuntimeWebNotFound,
    RuntimeWebOperation,
    RuntimeWebQuotaExceeded,
)
from azents.services.runtime_web.service import (
    RuntimeWebService,
    get_runtime_web_service,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    RuntimeWebActionErrorResponse,
    RuntimeWebApprovalRequest,
    RuntimeWebCloseRequest,
    RuntimeWebDirectCreateRequest,
    RuntimeWebExpectedRevisionRequest,
    RuntimeWebExposureRequest,
    RuntimeWebPrepareRequest,
    RuntimeWebServiceListResponse,
    RuntimeWebServiceResponse,
)

router = APIRouter()
RuntimeWebPort = Annotated[int, Path(ge=1, le=65_535)]

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_403_FORBIDDEN: {
        "model": RuntimeWebActionErrorResponse,
        "description": "The caller cannot disclose or manage this Session service.",
    },
    status.HTTP_404_NOT_FOUND: {
        "model": RuntimeWebActionErrorResponse,
        "description": "The service resource is unavailable or intentionally hidden.",
    },
    status.HTTP_409_CONFLICT: {
        "model": RuntimeWebActionErrorResponse,
        "description": "The service state or installation configuration changed.",
    },
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": RuntimeWebActionErrorResponse,
        "description": "A logical Runtime Web service quota is exhausted.",
    },
}


def _user_actor(member: WorkspaceMember) -> RuntimeWebActor:
    return RuntimeWebActor(
        kind=RuntimeWebRequesterKind.USER,
        actor_id=member.user_id,
        execution_id=member.session_id,
        call_id=None,
    )


def _operation(operation_key: str) -> RuntimeWebOperation:
    return RuntimeWebOperation(operation_key=operation_key)


def _raise_runtime_web_error(error: RuntimeWebError) -> NoReturn:
    match error:
        case RuntimeWebNotFound():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "scope": None},
            )
        case RuntimeWebAccessDenied():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "access_denied", "scope": None},
            )
        case RuntimeWebConflict():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "conflict", "scope": None},
            )
        case RuntimeWebQuotaExceeded(scope=scope):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"code": "quota_exceeded", "scope": scope},
            )
        case RuntimeWebConfigurationUnavailable():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "configuration_unavailable", "scope": None},
            )
        case _ as unreachable:
            assert_never(unreachable)


@router.put(
    "/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/services/{port}/endpoint",
    response_model=RuntimeWebServiceResponse,
    responses=_ERROR_RESPONSES,
)
async def prepare_runtime_web_endpoint(
    handle: str,
    agent_id: str,
    session_id: str,
    port: RuntimeWebPort,
    request_body: RuntimeWebPrepareRequest,
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeWebService, Depends(get_runtime_web_service)],
) -> RuntimeWebServiceResponse:
    """Prepare one stable Session-and-port endpoint without creating exposure."""
    result = await service.prepare_endpoint(
        workspace_id=member.workspace_id,
        agent_id=agent_id,
        session_id=session_id,
        user_id=member.user_id,
        port=port,
        label=request_body.label,
        actor=_user_actor(member),
        operation=_operation(request_body.operation_key),
    )
    match result:
        case Success(value):
            return RuntimeWebServiceResponse.convert_from(value)
        case Failure(error):
            _raise_runtime_web_error(error)
        case _ as unreachable:
            assert_never(unreachable)


@router.get(
    "/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/services",
    response_model=RuntimeWebServiceListResponse,
    responses=_ERROR_RESPONSES,
)
async def list_runtime_web_services(
    handle: str,
    agent_id: str,
    session_id: str,
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeWebService, Depends(get_runtime_web_service)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RuntimeWebServiceListResponse:
    """List bounded current Runtime Web service projections."""
    result = await service.list_services(
        workspace_id=member.workspace_id,
        agent_id=agent_id,
        session_id=session_id,
        user_id=member.user_id,
        offset=offset,
        limit=limit,
        actor=_user_actor(member),
    )
    match result:
        case Success(value):
            return RuntimeWebServiceListResponse.convert_from(value)
        case Failure(error):
            _raise_runtime_web_error(error)
        case _ as unreachable:
            assert_never(unreachable)


@router.get(
    "/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/services/{port}",
    response_model=RuntimeWebServiceResponse,
    responses=_ERROR_RESPONSES,
)
async def get_runtime_web_service_projection(
    handle: str,
    agent_id: str,
    session_id: str,
    port: RuntimeWebPort,
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeWebService, Depends(get_runtime_web_service)],
) -> RuntimeWebServiceResponse:
    """Return one current Runtime Web service projection."""
    result = await service.get_service(
        workspace_id=member.workspace_id,
        agent_id=agent_id,
        session_id=session_id,
        user_id=member.user_id,
        port=port,
        actor=_user_actor(member),
    )
    match result:
        case Success(value):
            return RuntimeWebServiceResponse.convert_from(value)
        case Failure(error):
            _raise_runtime_web_error(error)
        case _ as unreachable:
            assert_never(unreachable)


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/services/{port}/requests",
    response_model=RuntimeWebServiceResponse,
    responses=_ERROR_RESPONSES,
)
async def request_runtime_web_exposure(
    handle: str,
    agent_id: str,
    session_id: str,
    port: RuntimeWebPort,
    request_body: RuntimeWebExposureRequest,
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeWebService, Depends(get_runtime_web_service)],
) -> RuntimeWebServiceResponse:
    """Create or return the pending request without waiting for approval."""
    result = await service.request_exposure(
        workspace_id=member.workspace_id,
        agent_id=agent_id,
        session_id=session_id,
        user_id=member.user_id,
        port=port,
        label=request_body.label,
        actor=_user_actor(member),
        operation=_operation(request_body.operation_key),
    )
    match result:
        case Success(value):
            return RuntimeWebServiceResponse.convert_from(value)
        case Failure(error):
            _raise_runtime_web_error(error)
        case _ as unreachable:
            assert_never(unreachable)


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/services/{port}/direct-create",
    response_model=RuntimeWebServiceResponse,
    responses=_ERROR_RESPONSES,
)
async def direct_create_runtime_web_exposure(
    handle: str,
    agent_id: str,
    session_id: str,
    port: RuntimeWebPort,
    request_body: RuntimeWebDirectCreateRequest,
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeWebService, Depends(get_runtime_web_service)],
) -> RuntimeWebServiceResponse:
    """Directly create one user-confirmed finite exposure cycle."""
    result = await service.direct_create(
        workspace_id=member.workspace_id,
        agent_id=agent_id,
        session_id=session_id,
        user_id=member.user_id,
        port=port,
        label=request_body.label,
        actor=_user_actor(member),
        operation=_operation(request_body.operation_key),
        duration_seconds=request_body.duration_seconds,
        duration_configuration_revision=(request_body.duration_configuration_revision),
    )
    match result:
        case Success(value):
            return RuntimeWebServiceResponse.convert_from(value)
        case Failure(error):
            _raise_runtime_web_error(error)
        case _ as unreachable:
            assert_never(unreachable)


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/requests/{request_id}/approve",
    response_model=RuntimeWebServiceResponse,
    responses=_ERROR_RESPONSES,
)
async def approve_runtime_web_request(
    handle: str,
    agent_id: str,
    session_id: str,
    request_id: str,
    request_body: RuntimeWebApprovalRequest,
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeWebService, Depends(get_runtime_web_service)],
) -> RuntimeWebServiceResponse:
    """Approve one exact pending request and displayed duration."""
    result = await service.approve_request(
        workspace_id=member.workspace_id,
        agent_id=agent_id,
        session_id=session_id,
        user_id=member.user_id,
        actor=_user_actor(member),
        request_id=request_id,
        expected_revision=request_body.expected_revision,
        operation=_operation(request_body.operation_key),
        duration_seconds=request_body.duration_seconds,
        duration_configuration_revision=(request_body.duration_configuration_revision),
    )
    match result:
        case Success(value):
            return RuntimeWebServiceResponse.convert_from(value)
        case Failure(error):
            _raise_runtime_web_error(error)
        case _ as unreachable:
            assert_never(unreachable)


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/requests/{request_id}/reject",
    response_model=RuntimeWebServiceResponse,
    responses=_ERROR_RESPONSES,
)
async def reject_runtime_web_request(
    handle: str,
    agent_id: str,
    session_id: str,
    request_id: str,
    request_body: RuntimeWebExpectedRevisionRequest,
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeWebService, Depends(get_runtime_web_service)],
) -> RuntimeWebServiceResponse:
    """Reject one exact pending request."""
    result = await service.reject_request(
        workspace_id=member.workspace_id,
        agent_id=agent_id,
        session_id=session_id,
        user_id=member.user_id,
        actor=_user_actor(member),
        request_id=request_id,
        expected_revision=request_body.expected_revision,
        operation=_operation(request_body.operation_key),
    )
    match result:
        case Success(value):
            return RuntimeWebServiceResponse.convert_from(value)
        case Failure(error):
            _raise_runtime_web_error(error)
        case _ as unreachable:
            assert_never(unreachable)


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/requests/{request_id}/cancel",
    response_model=RuntimeWebServiceResponse,
    responses=_ERROR_RESPONSES,
)
async def cancel_runtime_web_request(
    handle: str,
    agent_id: str,
    session_id: str,
    request_id: str,
    request_body: RuntimeWebExpectedRevisionRequest,
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeWebService, Depends(get_runtime_web_service)],
) -> RuntimeWebServiceResponse:
    """Cancel one exact pending request without closing an active exposure."""
    result = await service.cancel_request(
        workspace_id=member.workspace_id,
        agent_id=agent_id,
        session_id=session_id,
        user_id=member.user_id,
        request_id=request_id,
        expected_revision=request_body.expected_revision,
        actor=_user_actor(member),
        operation=_operation(request_body.operation_key),
    )
    match result:
        case Success(value):
            return RuntimeWebServiceResponse.convert_from(value)
        case Failure(error):
            _raise_runtime_web_error(error)
        case _ as unreachable:
            assert_never(unreachable)


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/cycles/{cycle_id}/close",
    response_model=RuntimeWebServiceResponse,
    responses=_ERROR_RESPONSES,
)
async def close_runtime_web_cycle(
    handle: str,
    agent_id: str,
    session_id: str,
    cycle_id: str,
    request_body: RuntimeWebCloseRequest,
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeWebService, Depends(get_runtime_web_service)],
) -> RuntimeWebServiceResponse:
    """Close one exact active exposure without managing the application process."""
    result = await service.close_cycle(
        workspace_id=member.workspace_id,
        agent_id=agent_id,
        session_id=session_id,
        user_id=member.user_id,
        cycle_id=cycle_id,
        expected_endpoint_revision=request_body.expected_endpoint_revision,
        actor=_user_actor(member),
        operation=_operation(request_body.operation_key),
    )
    match result:
        case Success(value):
            return RuntimeWebServiceResponse.convert_from(value)
        case Failure(error):
            _raise_runtime_web_error(error)
        case _ as unreachable:
            assert_never(unreachable)


def mount(mounter: RouteMounter) -> None:
    """Mount Public Runtime Web v1 routes."""
    mounter(
        router,
        prefix="/runtime-web/v1",
        tag="Runtime Web v1",
        description=dedent(
            """
            Runtime Web service control API (Public)

            Stable Session-and-port endpoint preparation, asynchronous exposure
            requests, explicit Session-authorized approval, finite cycles, and
            closure without Runtime process management.
            """
        ),
    )
