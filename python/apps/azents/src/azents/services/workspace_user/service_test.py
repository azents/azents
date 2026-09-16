"""WorkspaceUser service tests."""

import datetime
from unittest.mock import AsyncMock

from azcommon.result import Failure, Success

from azents.core.enums import WorkspaceUserRole
from azents.repos.workspace_user.data import NotFound as RepositoryNotFound
from azents.repos.workspace_user.data import WorkspaceUser
from azents.repos.workspace_user.operations import (
    DeletedWorkspaceUser,
    WorkspaceOwnershipTransfer,
    WorkspaceUserOperationRepository,
    WorkspaceUserOutsideWorkspace,
    WorkspaceUserOwnerAlreadyExists,
    WorkspaceUserOwnerLocked,
)
from azents.testing.types import require_instance

from . import WorkspaceUserService
from .data import (
    CannotModifyOwner,
    CannotModifySelf,
    InvalidRole,
    NotFound,
    NotMemberOfWorkspace,
    OwnerAlreadyExists,
    WorkspaceUserCreateInput,
)


def _now() -> datetime.datetime:
    """Return one stable aware timestamp for domain fixtures."""
    return datetime.datetime(2026, 9, 16, tzinfo=datetime.UTC)


def _workspace_user(
    *,
    workspace_user_id: str = "workspace-user-1",
    workspace_id: str = "workspace-1",
    user_id: str = "user-1",
    role: WorkspaceUserRole = WorkspaceUserRole.MEMBER,
) -> WorkspaceUser:
    """Build a WorkspaceUser fixture."""
    return WorkspaceUser(
        id=workspace_user_id,
        workspace_id=workspace_id,
        user_id=user_id,
        name="Member",
        role=role,
        created_at=_now(),
        updated_at=_now(),
    )


class _RecordingInvalidationPublisher:
    """Record committed User invalidations without external side effects."""

    def __init__(self) -> None:
        self.user_ids: list[str] = []

    async def publish_runtime_terminal_invalidation(self, runtime_id: str) -> None:
        """Accept one Runtime invalidation."""
        del runtime_id

    async def publish_user_terminal_invalidation(self, user_id: str) -> None:
        """Record one User invalidation."""
        self.user_ids.append(user_id)

    async def publish_authentication_session_terminal_invalidation(
        self,
        authentication_session_id: str,
    ) -> None:
        """Accept one authentication Session invalidation."""
        del authentication_session_id

    async def publish_agent_session_terminal_invalidation(
        self,
        agent_session_id: str,
    ) -> None:
        """Accept one Agent Session invalidation."""
        del agent_session_id


def _service(
    *,
    operations: AsyncMock | None = None,
    publisher: _RecordingInvalidationPublisher | None = None,
) -> WorkspaceUserService:
    """Build a service with deterministic test dependencies."""
    return WorkspaceUserService(
        operations=require_instance(
            operations or AsyncMock(spec=WorkspaceUserOperationRepository),
            WorkspaceUserOperationRepository,
        ),
        terminal_invalidation_publisher=publisher or _RecordingInvalidationPublisher(),
    )


async def test_create_maps_existing_owner() -> None:
    """Owner creation maps the repository conflict to a service error."""
    operations = AsyncMock(spec=WorkspaceUserOperationRepository)
    operations.create_by_handle.return_value = Failure(
        WorkspaceUserOwnerAlreadyExists(workspace_user_id="owner-1")
    )
    service = _service(operations=operations)

    result = await service.create(
        WorkspaceUserCreateInput(
            workspace_handle="workspace",
            user_id="user-2",
            name="Second owner",
            role=WorkspaceUserRole.OWNER,
        )
    )

    assert isinstance(result, Failure)
    assert result.error == OwnerAlreadyExists(workspace_user_id="owner-1")


async def test_update_role_rejects_self_before_database_work() -> None:
    """A member cannot change their own role."""
    operations = AsyncMock(spec=WorkspaceUserOperationRepository)
    service = _service(operations=operations)

    result = await service.update_role(
        "workspace-user-1",
        "workspace-user-1",
        WorkspaceUserRole.MANAGER,
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, CannotModifySelf)
    operations.update_non_owner_role.assert_not_awaited()


async def test_update_role_admin_rejects_owner_assignment_before_database_work() -> (
    None
):
    """Admin role updates must use ownership transfer for Owner assignment."""
    operations = AsyncMock(spec=WorkspaceUserOperationRepository)
    service = _service(operations=operations)

    result = await service.update_role_admin(
        "workspace-user-1", WorkspaceUserRole.OWNER
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, InvalidRole)
    operations.update_non_owner_role.assert_not_awaited()


async def test_update_role_admin_maps_owner_lock() -> None:
    """Admin role updates preserve the Owner lock as a service error."""
    operations = AsyncMock(spec=WorkspaceUserOperationRepository)
    operations.update_non_owner_role.return_value = Failure(WorkspaceUserOwnerLocked())
    service = _service(operations=operations)

    result = await service.update_role_admin(
        "workspace-user-1", WorkspaceUserRole.MANAGER
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, CannotModifyOwner)


async def test_update_role_publishes_after_success() -> None:
    """Committed role updates invalidate the affected User."""
    operations = AsyncMock(spec=WorkspaceUserOperationRepository)
    publisher = _RecordingInvalidationPublisher()
    operations.update_non_owner_role.return_value = Success(_workspace_user())
    service = _service(operations=operations, publisher=publisher)

    result = await service.update_role(
        "actor-1",
        "workspace-user-1",
        WorkspaceUserRole.MANAGER,
    )

    assert isinstance(result, Success)
    assert publisher.user_ids == ["user-1"]


async def test_delete_force_maps_not_found_without_invalidation() -> None:
    """Failed deletion does not publish an authority invalidation."""
    operations = AsyncMock(spec=WorkspaceUserOperationRepository)
    publisher = _RecordingInvalidationPublisher()
    operations.delete_non_owner.return_value = Failure(
        RepositoryNotFound(workspace_user_id="workspace-user-1")
    )
    service = _service(operations=operations, publisher=publisher)

    result = await service.delete_force("workspace-user-1")

    assert isinstance(result, Failure)
    assert result.error == NotFound(workspace_user_id="workspace-user-1")
    assert publisher.user_ids == []


async def test_delete_force_publishes_committed_deletion() -> None:
    """Committed deletion invalidates the affected User."""
    operations = AsyncMock(spec=WorkspaceUserOperationRepository)
    publisher = _RecordingInvalidationPublisher()
    operations.delete_non_owner.return_value = Success(
        DeletedWorkspaceUser(user_id="user-1")
    )
    service = _service(operations=operations, publisher=publisher)

    result = await service.delete_force("workspace-user-1")

    assert isinstance(result, Success)
    assert publisher.user_ids == ["user-1"]


async def test_transfer_ownership_maps_cross_workspace_target() -> None:
    """Ownership transfer maps repository scope rejection to a service error."""
    operations = AsyncMock(spec=WorkspaceUserOperationRepository)
    operations.transfer_ownership.return_value = Failure(
        WorkspaceUserOutsideWorkspace(workspace_user_id="workspace-user-1")
    )
    service = _service(operations=operations)

    result = await service.transfer_ownership("workspace-1", "workspace-user-1")

    assert isinstance(result, Failure)
    assert result.error == NotMemberOfWorkspace(workspace_user_id="workspace-user-1")


async def test_transfer_ownership_publishes_both_affected_users() -> None:
    """Committed ownership transfer invalidates old and new Owners."""
    operations = AsyncMock(spec=WorkspaceUserOperationRepository)
    publisher = _RecordingInvalidationPublisher()
    operations.transfer_ownership.return_value = Success(
        WorkspaceOwnershipTransfer(
            owner=_workspace_user(user_id="new-owner", role=WorkspaceUserRole.OWNER),
            previous_owner_user_id="previous-owner",
            changed=True,
        )
    )
    service = _service(operations=operations, publisher=publisher)

    result = await service.transfer_ownership("workspace-1", "workspace-user-1")

    assert isinstance(result, Success)
    assert publisher.user_ids == ["previous-owner", "new-owner"]


async def test_transfer_ownership_to_current_owner_skips_invalidation() -> None:
    """Idempotent ownership transfer does not invalidate unchanged authority."""
    operations = AsyncMock(spec=WorkspaceUserOperationRepository)
    publisher = _RecordingInvalidationPublisher()
    operations.transfer_ownership.return_value = Success(
        WorkspaceOwnershipTransfer(
            owner=_workspace_user(user_id="owner", role=WorkspaceUserRole.OWNER),
            previous_owner_user_id=None,
            changed=False,
        )
    )
    service = _service(operations=operations, publisher=publisher)

    result = await service.transfer_ownership("workspace-1", "workspace-user-1")

    assert isinstance(result, Success)
    assert publisher.user_ids == []
