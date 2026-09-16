"""WorkspaceUser Admin API route tests."""

from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure
from fastapi import HTTPException, status

from azents.core.enums import WorkspaceUserRole
from azents.repos.workspace_user.data import UserNotFound, WorkspaceUserAlreadyExists
from azents.services.workspace_user import WorkspaceUserService
from azents.services.workspace_user.data import (
    CannotModifyOwner,
    InvalidRole,
    OwnerAlreadyExists,
)
from azents.testing.types import is_string_object_dict

from . import (
    create_workspace_user,
    delete_workspace_user,
    update_workspace_user_role,
)
from .data import WorkspaceUserCreateRequest, WorkspaceUserRoleUpdateRequest


async def test_create_workspace_user_maps_duplicate_membership_to_conflict() -> None:
    """The Admin API exposes duplicate membership as an expected conflict."""
    service = AsyncMock(spec=WorkspaceUserService)
    service.create.return_value = Failure(
        WorkspaceUserAlreadyExists(workspace_id="workspace-1", user_id="user-1")
    )

    with pytest.raises(HTTPException) as captured:
        await create_workspace_user(
            service,
            WorkspaceUserCreateRequest(
                workspace_handle="workspace",
                user_id="user-1",
                name="Member",
                role=WorkspaceUserRole.MEMBER,
            ),
        )

    assert captured.value.status_code == status.HTTP_409_CONFLICT
    detail = captured.value.detail
    assert is_string_object_dict(detail)
    assert detail["code"] == "workspace_user_already_exists"


async def test_create_workspace_user_maps_existing_owner_to_conflict() -> None:
    """Creating a second Owner instructs the caller to transfer ownership."""
    service = AsyncMock(spec=WorkspaceUserService)
    service.create.return_value = Failure(
        OwnerAlreadyExists(workspace_user_id="owner-1")
    )

    with pytest.raises(HTTPException) as captured:
        await create_workspace_user(
            service,
            WorkspaceUserCreateRequest(
                workspace_handle="workspace",
                user_id="user-2",
                name="Second owner",
                role=WorkspaceUserRole.OWNER,
            ),
        )

    assert captured.value.status_code == status.HTTP_409_CONFLICT
    detail = captured.value.detail
    assert is_string_object_dict(detail)
    assert detail["code"] == "workspace_owner_already_exists"


async def test_create_workspace_user_maps_missing_user_to_not_found() -> None:
    """A User deleted after selection is reported as a missing Admin resource."""
    service = AsyncMock(spec=WorkspaceUserService)
    service.create.return_value = Failure(UserNotFound(user_id="user-1"))

    with pytest.raises(HTTPException) as captured:
        await create_workspace_user(
            service,
            WorkspaceUserCreateRequest(
                workspace_handle="workspace",
                user_id="user-1",
                name="Deleted user",
                role=WorkspaceUserRole.MEMBER,
            ),
        )

    assert captured.value.status_code == status.HTTP_404_NOT_FOUND


async def test_update_workspace_user_role_blocks_direct_owner_assignment() -> None:
    """Owner assignment remains exclusive to the transfer endpoint."""
    service = AsyncMock(spec=WorkspaceUserService)
    service.update_role_admin.return_value = Failure(InvalidRole())

    with pytest.raises(HTTPException) as captured:
        await update_workspace_user_role(
            service,
            workspace_user_id="workspace-user-1",
            request=WorkspaceUserRoleUpdateRequest(role=WorkspaceUserRole.OWNER),
        )

    assert captured.value.status_code == status.HTTP_400_BAD_REQUEST


async def test_update_workspace_user_role_blocks_current_owner_change() -> None:
    """A current Owner must be replaced through ownership transfer first."""
    service = AsyncMock(spec=WorkspaceUserService)
    service.update_role_admin.return_value = Failure(CannotModifyOwner())

    with pytest.raises(HTTPException) as captured:
        await update_workspace_user_role(
            service,
            workspace_user_id="owner-1",
            request=WorkspaceUserRoleUpdateRequest(role=WorkspaceUserRole.MANAGER),
        )

    assert captured.value.status_code == status.HTTP_409_CONFLICT
    detail = captured.value.detail
    assert is_string_object_dict(detail)
    assert detail["code"] == "workspace_owner_role_locked"


async def test_delete_workspace_user_blocks_current_owner() -> None:
    """Admin deletion reports the required ownership-transfer recovery action."""
    service = AsyncMock(spec=WorkspaceUserService)
    service.delete_force.return_value = Failure(CannotModifyOwner())

    with pytest.raises(HTTPException) as captured:
        await delete_workspace_user(service, workspace_user_id="owner-1")

    assert captured.value.status_code == status.HTTP_409_CONFLICT
    detail = captured.value.detail
    assert is_string_object_dict(detail)
    assert detail["code"] == "workspace_owner_delete_blocked"
