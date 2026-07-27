"""Runtime Execution v1 Public API."""

from textwrap import dedent
from typing import Annotated, NoReturn

from azcommon.uuid import uuid7
from fastapi import APIRouter, Depends, HTTPException, Query, status

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.auth.permissions import Permission, Permissions
from azents.core.runtime_execution_policy import RuntimeExecutionRestrictionExpansion
from azents.repos.runtime_execution_policy.data import (
    RuntimeExecutionPolicyAuditEvent,
)
from azents.services.runtime_execution_policy.application_service import (
    RuntimeExecutionPolicyApplicationService,
)
from azents.services.runtime_execution_policy.service import (
    AgentRuntimeExecutionSettingMutation,
    RuntimeExecutionPolicyService,
    RuntimeExecutionPolicyUnavailable,
    RuntimeExecutionPolicyVersionConflict,
    WorkspaceRuntimeExecutionPolicyMutation,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    AgentRuntimeExecutionPolicyApplyResponse,
    AgentRuntimeExecutionPolicyReplaceRequest,
    AgentRuntimeExecutionPolicyResponse,
    RuntimeExecutionPolicyAuditEventResponse,
    RuntimeExecutionPolicyAuditListResponse,
    WorkspaceRuntimeExecutionPolicyReplaceRequest,
    WorkspaceRuntimeExecutionPolicyResponse,
    WorkspaceRuntimeExecutionProfileListResponse,
    WorkspaceRuntimeExecutionProfileResponse,
)

router = APIRouter()


@router.get("/workspaces/{handle}/policy")
async def get_workspace_policy(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeExecutionPolicyService, Depends()],
) -> WorkspaceRuntimeExecutionPolicyResponse:
    """Return the current safe Workspace execution policy."""
    _require_workspace_permission(
        member,
        Permissions.RUNTIME_EXECUTION_POLICY_READ,
    )
    policy = await service.get_workspace_policy(member.workspace_id)
    return WorkspaceRuntimeExecutionPolicyResponse.convert_from(
        policy,
        capabilities=service.get_management_capabilities(),
    )


@router.put("/workspaces/{handle}/policy")
async def replace_workspace_policy(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeExecutionPolicyService, Depends()],
    request_body: WorkspaceRuntimeExecutionPolicyReplaceRequest,
) -> WorkspaceRuntimeExecutionPolicyResponse:
    """Replace Workspace restrictions and complete Profile allowance."""
    _require_workspace_permission(
        member,
        Permissions.RUNTIME_EXECUTION_POLICY_WRITE,
    )
    try:
        policy = await service.replace_workspace_for_manager(
            member.workspace_id,
            WorkspaceRuntimeExecutionPolicyMutation(
                expected_version=request_body.expected_version,
                restriction=request_body.restriction,
                allowed_profile_ids=frozenset(request_body.allowed_profile_ids),
                actor_workspace_user_id=member.workspace_user_id,
                correlation_id=uuid7().hex,
            ),
            role=member.role,
        )
    except (
        RuntimeExecutionPolicyUnavailable,
        RuntimeExecutionPolicyVersionConflict,
        RuntimeExecutionRestrictionExpansion,
    ) as error:
        _raise_policy_error(error)
    return WorkspaceRuntimeExecutionPolicyResponse.convert_from(
        policy,
        capabilities=service.get_management_capabilities(),
    )


@router.get("/workspaces/{handle}/profiles")
async def list_workspace_profiles(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeExecutionPolicyService, Depends()],
    *,
    include_retired: bool = False,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> WorkspaceRuntimeExecutionProfileListResponse:
    """List Profiles with Workspace-level availability reasons."""
    _require_workspace_permission(
        member,
        Permissions.RUNTIME_EXECUTION_POLICY_READ,
    )
    profiles = await service.list_workspace_profiles(
        member.workspace_id,
        include_retired=include_retired,
        offset=offset,
        limit=limit,
    )
    return WorkspaceRuntimeExecutionProfileListResponse(
        items=[
            WorkspaceRuntimeExecutionProfileResponse.convert_from(profile)
            for profile in profiles
        ]
    )


@router.get("/workspaces/{handle}/policy/audit-events")
async def list_workspace_audit_events(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeExecutionPolicyService, Depends()],
    *,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RuntimeExecutionPolicyAuditListResponse:
    """List metadata-only Workspace execution-policy audit history."""
    _require_workspace_permission(
        member,
        Permissions.RUNTIME_EXECUTION_POLICY_READ,
    )
    events = await service.list_workspace_audit_events(
        member.workspace_id,
        offset=offset,
        limit=limit,
    )
    return _audit_list(events)


@router.get("/workspaces/{handle}/agents/{agent_id}/settings")
async def get_agent_policy(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeExecutionPolicyService, Depends()],
    *,
    agent_id: str,
) -> AgentRuntimeExecutionPolicyResponse:
    """Return configured Agent execution intent and effective preview."""
    try:
        policy = await service.get_agent_policy_for_manager(
            agent_id,
            workspace_id=member.workspace_id,
            workspace_user_id=member.workspace_user_id,
            role=member.role,
        )
    except RuntimeExecutionPolicyUnavailable as error:
        _raise_policy_error(error)
    return AgentRuntimeExecutionPolicyResponse.convert_from(policy)


@router.put("/workspaces/{handle}/agents/{agent_id}/settings")
async def replace_agent_policy(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeExecutionPolicyService, Depends()],
    request_body: AgentRuntimeExecutionPolicyReplaceRequest,
    *,
    agent_id: str,
) -> AgentRuntimeExecutionPolicyResponse:
    """Replace configured Agent Profile selection and restrictive override."""
    try:
        policy = await service.replace_agent_setting_for_manager(
            agent_id,
            AgentRuntimeExecutionSettingMutation(
                expected_version=request_body.expected_version,
                profile_id=request_body.profile_id,
                restriction=request_body.restriction,
                actor_workspace_user_id=member.workspace_user_id,
                correlation_id=uuid7().hex,
            ),
            workspace_id=member.workspace_id,
            workspace_user_id=member.workspace_user_id,
            role=member.role,
        )
    except (
        RuntimeExecutionPolicyUnavailable,
        RuntimeExecutionPolicyVersionConflict,
        RuntimeExecutionRestrictionExpansion,
    ) as error:
        _raise_policy_error(error)
    return AgentRuntimeExecutionPolicyResponse.convert_from(policy)


@router.post("/workspaces/{handle}/agents/{agent_id}/apply")
async def apply_agent_policy(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeExecutionPolicyApplicationService, Depends()],
    *,
    agent_id: str,
) -> AgentRuntimeExecutionPolicyApplyResponse:
    """Apply current valid Agent execution intent to its Runtime."""
    try:
        result = await service.apply_agent_for_manager(
            agent_id=agent_id,
            workspace_id=member.workspace_id,
            workspace_user_id=member.workspace_user_id,
            role=member.role,
            actor_workspace_user_id=member.workspace_user_id,
            correlation_id=uuid7().hex,
        )
    except RuntimeExecutionPolicyUnavailable as error:
        _raise_policy_error(error)
    return AgentRuntimeExecutionPolicyApplyResponse.convert_from(result)


@router.get("/workspaces/{handle}/agents/{agent_id}/audit-events")
async def list_agent_audit_events(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeExecutionPolicyService, Depends()],
    *,
    agent_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RuntimeExecutionPolicyAuditListResponse:
    """List metadata-only Agent execution-policy audit history."""
    try:
        events = await service.list_agent_audit_events_for_manager(
            agent_id,
            workspace_id=member.workspace_id,
            workspace_user_id=member.workspace_user_id,
            role=member.role,
            offset=offset,
            limit=limit,
        )
    except RuntimeExecutionPolicyUnavailable as error:
        _raise_policy_error(error)
    return _audit_list(events)


def _audit_list(
    events: list[RuntimeExecutionPolicyAuditEvent],
) -> RuntimeExecutionPolicyAuditListResponse:
    """Convert authorized audit events to the metadata-only response."""
    return RuntimeExecutionPolicyAuditListResponse(
        items=[
            RuntimeExecutionPolicyAuditEventResponse.convert_from(event)
            for event in events
        ]
    )


def _require_workspace_permission(
    member: WorkspaceMember,
    permission: Permission,
) -> None:
    """Enforce Workspace execution-policy authority."""
    if not member.has_permission(permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No Runtime Execution policy permission.",
        )


def _raise_policy_error(error: Exception) -> NoReturn:
    """Map bounded execution-policy failures to safe Public responses."""
    if isinstance(error, RuntimeExecutionPolicyVersionConflict):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "stale_execution_policy_version",
                "current_version": error.current_version,
            },
        ) from error
    if isinstance(error, RuntimeExecutionRestrictionExpansion):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "execution_policy_expansion_rejected",
                "path": error.path,
                "governing_layer": error.governing_layer.value,
            },
        ) from error
    if isinstance(error, RuntimeExecutionPolicyUnavailable):
        if error.code in {"agent_not_found", "profile_not_found"}:
            status_code = status.HTTP_404_NOT_FOUND
        elif error.code in {
            "agent_access_denied",
            "workspace_policy_access_denied",
        }:
            status_code = status.HTTP_403_FORBIDDEN
        else:
            status_code = status.HTTP_409_CONFLICT
        raise HTTPException(
            status_code=status_code,
            detail={"code": error.code},
        ) from error
    raise error


def mount(mounter: RouteMounter) -> None:
    """Mount Runtime Execution Public routes."""
    mounter(
        router,
        prefix="/runtime-execution/v1",
        tag="Runtime Execution v1",
        description=dedent(
            """
            Runtime Execution API (Public)

            Workspace policy and Agent execution-intent management.
            """
        ),
    )
