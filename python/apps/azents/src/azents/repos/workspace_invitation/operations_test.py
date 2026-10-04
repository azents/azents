"""Isolated PostgreSQL coverage for completed Workspace membership operations."""

import asyncio
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.auth.deps import CurrentUser, WorkspaceMember
from azents.core.email.service import EmailService
from azents.core.enums import (
    InvitationStatus,
    JoinRequestStatus,
    SignupTokenDeliveryMethod,
    WorkspaceUserRole,
)
from azents.core.workspace import WorkspaceCreate
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.user_email import UserEmailRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_invitation import WorkspaceInvitationRepository
from azents.repos.workspace_invitation.data import (
    NotFound,
    WorkspaceInvitation,
    WorkspaceInvitationCreate,
)
from azents.repos.workspace_invitation.operation_data import (
    AlreadyMember,
    AlreadyProcessed,
    InvitationNotFound,
    WorkspaceNotFound,
)
from azents.repos.workspace_invitation.operations import (
    WorkspaceInvitationOperationRepository,
)
from azents.repos.workspace_join_request import WorkspaceJoinRequestRepository
from azents.repos.workspace_join_request.data import (
    WorkspaceJoinRequest,
)
from azents.repos.workspace_join_request.operation_data import (
    AlreadyMember as JoinAlreadyMember,
)
from azents.repos.workspace_join_request.operation_data import (
    JoinRequestNotFound,
    PendingRequestExists,
)
from azents.repos.workspace_join_request.operations import (
    WorkspaceJoinRequestOperationRepository,
)
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.services.signup_token import SignupTokenService
from azents.services.signup_token.data import (
    CreateSignupTokenInput,
    SignupTokenOutput,
    SignupTokenWithPlaintextOutput,
)
from azents.services.workspace_invitation import WorkspaceInvitationService
from azents.services.workspace_invitation.data import (
    AlreadyMember as ServiceAlreadyMember,
)
from azents.services.workspace_invitation.data import (
    AlreadyProcessed as ServiceAlreadyProcessed,
)
from azents.services.workspace_invitation.data import (
    CreateInvitationInput,
)
from azents.services.workspace_invitation.data import (
    InvitationNotFound as ServiceInvitationNotFound,
)
from azents.services.workspace_join_request import WorkspaceJoinRequestService
from azents.services.workspace_join_request.data import (
    AlreadyMember as ServiceJoinAlreadyMember,
)
from azents.services.workspace_join_request.data import (
    JoinRequestNotFound as ServiceJoinRequestNotFound,
)
from azents.services.workspace_join_request.data import (
    PendingRequestExists as ServicePendingRequestExists,
)
from azents.testing.types import require_instance


@dataclass
class MembershipFixture:
    """Committed identities and transaction-observing operation collaborators."""

    workspace_id: str
    handle: str
    owner_id: str
    owner_membership_id: str
    user_id: str
    stranger_id: str
    email: str
    invitation: WorkspaceInvitationOperationRepository
    join_request: WorkspaceJoinRequestOperationRepository
    session_manager: SessionManager[WriteSession]
    sessions: list[AsyncSession]

    def assert_closed(self) -> None:
        """Require all previously opened operation transactions to have ended."""
        assert self.sessions
        assert all(not session.in_transaction() for session in self.sessions)

    def member(self) -> WorkspaceMember:
        """Build an already-authorized manager context."""
        return WorkspaceMember(
            user_id=self.owner_id,
            workspace_id=self.workspace_id,
            workspace_user_id=self.owner_membership_id,
            role=WorkspaceUserRole.OWNER,
            permissions=set(),
            session_id="auth-session",
        )

    async def create_invitation(self) -> WorkspaceInvitation:
        """Create an invitation for the fixture's nonmember."""
        result = await self.invitation.create(
            WorkspaceInvitationCreate(
                workspace_id=self.workspace_id,
                email=self.email,
                role=WorkspaceUserRole.MANAGER,
                invited_by=self.owner_membership_id,
            )
        )
        assert isinstance(result, Success)
        self.assert_closed()
        return result.value.invitation

    async def create_request(self) -> WorkspaceJoinRequest:
        """Commit a request for the fixture's nonmember."""
        result = await self.join_request.request_join(
            user_id=self.user_id, workspace_handle=self.handle, message="Join me"
        )
        assert isinstance(result, Success)
        self.assert_closed()
        return result.value.join_request


@pytest_asyncio.fixture
async def membership(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> AsyncGenerator[MembershipFixture, None]:
    """Seed committed records and use independent production transaction scopes."""
    del latest_db_schema
    suffix = uuid4().hex
    handle = f"membership-{suffix}"
    email = f"target-{suffix}@example.com"
    manager = create_read_write_session_manager(rdb_engine)
    async with manager() as session:
        owner = await UserRepository().create(
            session, UserCreate(email=f"owner-{suffix}@example.com")
        )
        user = await UserRepository().create(session, UserCreate(email=email))
        stranger = await UserRepository().create(
            session, UserCreate(email=f"stranger-{suffix}@example.com")
        )
        workspace = await WorkspaceRepository().create(
            session, WorkspaceCreate(name="Membership", handle=handle)
        )
        assert isinstance(workspace, Success)
        workspace_id = await WorkspaceRepository().resolve_id(session, handle)
        assert workspace_id is not None
        owner_membership = await WorkspaceUserRepository().create(
            session,
            WorkspaceUserCreate(
                workspace_id=workspace_id,
                user_id=owner.id,
                name="Owner",
                role=WorkspaceUserRole.OWNER,
            ),
        )
        assert isinstance(owner_membership, Success)
    sessions: list[AsyncSession] = []

    @asynccontextmanager
    async def observed_manager() -> AsyncGenerator[WriteSession, None]:
        async with manager() as current:
            sessions.append(current.write_session)
            yield current

    fixture = MembershipFixture(
        workspace_id=workspace_id,
        handle=handle,
        owner_id=owner.id,
        owner_membership_id=owner_membership.value.id,
        user_id=user.id,
        stranger_id=stranger.id,
        email=email,
        invitation=WorkspaceInvitationOperationRepository(
            invitation_repo=WorkspaceInvitationRepository(),
            workspace_repo=WorkspaceRepository(),
            workspace_user_repo=WorkspaceUserRepository(),
            user_email_repo=UserEmailRepository(),
            join_request_repo=WorkspaceJoinRequestRepository(),
            session_manager=observed_manager,
        ),
        join_request=WorkspaceJoinRequestOperationRepository(
            join_request_repo=WorkspaceJoinRequestRepository(),
            workspace_repo=WorkspaceRepository(),
            workspace_user_repo=WorkspaceUserRepository(),
            session_manager=observed_manager,
        ),
        session_manager=observed_manager,
        sessions=sessions,
    )
    try:
        yield fixture
    finally:
        async with manager() as session:
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == workspace_id)
            )
            await session.write_session.execute(
                sa.delete(RDBUser).where(
                    RDBUser.id.in_([owner.id, user.id, stranger.id])
                )
            )


async def test_invitation_autoapproval_atomic_success(
    membership: MembershipFixture,
) -> None:
    """Invitation, membership and request deletion commit together."""
    request = await membership.create_request()
    invitation = await membership.create_invitation()
    assert invitation.status == InvitationStatus.PENDING
    async with membership.session_manager() as session:
        member = await WorkspaceUserRepository().get_by_workspace_and_user(
            session, membership.workspace_id, membership.user_id
        )
        assert member is not None
        assert member.role == WorkspaceUserRole.MANAGER
        assert member.name == membership.email.split("@")[0]
        assert await WorkspaceJoinRequestRepository().get(session, request.id) is None
    duplicate = await membership.invitation.create(
        WorkspaceInvitationCreate(
            workspace_id=membership.workspace_id,
            email=membership.email,
            role=WorkspaceUserRole.MEMBER,
            invited_by=membership.owner_membership_id,
        )
    )
    assert isinstance(duplicate, Failure)
    assert duplicate.error == AlreadyMember(email=membership.email)
    membership.assert_closed()


@pytest.mark.parametrize("cancel", [False, True])
async def test_invitation_autoapproval_rolls_back(
    membership: MembershipFixture, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    """A final write failure or cancellation preserves request and nonmembership."""
    request = await membership.create_request()

    async def fail_create(
        session: WriteSession, create: WorkspaceInvitationCreate
    ) -> WorkspaceInvitation:
        del session, create
        if cancel:
            raise asyncio.CancelledError
        raise RuntimeError("Injected invitation failure")

    monkeypatch.setattr(
        membership.invitation.invitation_repo, "create_or_reinvite", fail_create
    )
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
        await membership.create_invitation()
    membership.assert_closed()
    async with membership.session_manager() as session:
        assert (
            await WorkspaceUserRepository().get_by_workspace_and_user(
                session, membership.workspace_id, membership.user_id
            )
            is None
        )
        assert (
            await WorkspaceJoinRequestRepository().get(session, request.id) is not None
        )
        assert not (
            await WorkspaceInvitationRepository().list_by_workspace(
                session, membership.workspace_id
            )
        ).items


@pytest.mark.parametrize(
    "status", [InvitationStatus.ACCEPTED, InvitationStatus.DECLINED]
)
async def test_invitation_ownership_processing_and_lists(
    membership: MembershipFixture, status: InvitationStatus
) -> None:
    """Owned pending-only processing, hidden ownership and lists retain contracts."""
    invitation = await membership.create_invitation()
    received = await membership.invitation.list_received(membership.user_id)
    assert [item.invitation.id for item in received] == [invitation.id]
    assert received[0].workspace.name == "Membership"
    assert await membership.invitation.list_received(membership.stranger_id) == []
    my_invitation = await membership.invitation.get_my_invitation(
        user_id=membership.user_id, workspace_handle=membership.handle
    )
    assert isinstance(my_invitation, Success) and my_invitation.value == invitation
    listed = await membership.invitation.list_by_workspace_handle(membership.handle)
    assert isinstance(listed, Success) and listed.value.items == [invitation]
    hidden = await membership.invitation.process(
        user_id=membership.stranger_id, invitation_id=invitation.id, status=status
    )
    assert isinstance(hidden, Failure) and hidden.error == InvitationNotFound(
        invitation_id=invitation.id
    )
    result = await membership.invitation.process(
        user_id=membership.user_id, invitation_id=invitation.id, status=status
    )
    assert isinstance(result, Success) and result.value.status == status
    repeated = await membership.invitation.process(
        user_id=membership.user_id, invitation_id=invitation.id, status=status
    )
    assert isinstance(repeated, Failure) and repeated.error == AlreadyProcessed(
        invitation_id=invitation.id, status=status
    )
    async with membership.session_manager() as session:
        member = await WorkspaceUserRepository().get_by_workspace_and_user(
            session, membership.workspace_id, membership.user_id
        )
        if status == InvitationStatus.ACCEPTED:
            assert member is not None and member.role == invitation.role
        else:
            assert member is None
    membership.assert_closed()


@pytest.mark.parametrize("typed_failure", [False, True])
async def test_acceptance_status_failure_rolls_back_membership(
    membership: MembershipFixture, monkeypatch: pytest.MonkeyPatch, typed_failure: bool
) -> None:
    """Both exceptional and absent-final-row outcomes roll back the first write."""
    invitation = await membership.create_invitation()

    async def fail_status(
        session: WriteSession, invitation_id: str, status: InvitationStatus
    ) -> Result[WorkspaceInvitation, NotFound]:
        del session, status
        if typed_failure:
            return Failure(NotFound(invitation_id=invitation_id))
        raise RuntimeError("Injected status failure")

    monkeypatch.setattr(
        membership.invitation.invitation_repo, "update_status", fail_status
    )
    if typed_failure:
        result = await membership.invitation.process(
            user_id=membership.user_id,
            invitation_id=invitation.id,
            status=InvitationStatus.ACCEPTED,
        )
        assert isinstance(result, Failure) and result.error == InvitationNotFound(
            invitation_id=invitation.id
        )
    else:
        with pytest.raises(RuntimeError, match="Injected status"):
            await membership.invitation.process(
                user_id=membership.user_id,
                invitation_id=invitation.id,
                status=InvitationStatus.ACCEPTED,
            )
    membership.assert_closed()
    async with membership.session_manager() as session:
        assert (
            await WorkspaceUserRepository().get_by_workspace_and_user(
                session, membership.workspace_id, membership.user_id
            )
            is None
        )
        stored = await WorkspaceInvitationRepository().get(session, invitation.id)
        assert stored is not None and stored.status == InvitationStatus.PENDING


async def test_reinvite_and_delete(membership: MembershipFixture) -> None:
    """Declined invitations reset to pending with updated role and preserve identity."""
    invitation = await membership.create_invitation()
    await membership.invitation.process(
        user_id=membership.user_id,
        invitation_id=invitation.id,
        status=InvitationStatus.DECLINED,
    )
    reinvited = await membership.invitation.create(
        WorkspaceInvitationCreate(
            workspace_id=membership.workspace_id,
            email=membership.email,
            role=WorkspaceUserRole.MEMBER,
            invited_by=membership.owner_membership_id,
        )
    )
    assert isinstance(reinvited, Success)
    assert reinvited.value.invitation.id == invitation.id
    assert reinvited.value.invitation.role == WorkspaceUserRole.MEMBER
    assert reinvited.value.invitation.status == InvitationStatus.PENDING
    await membership.invitation.delete(invitation.id)
    assert not (
        await membership.invitation.list_by_workspace(membership.workspace_id)
    ).items
    membership.assert_closed()


async def test_join_request_new_pending_muted_rerequest(
    membership: MembershipFixture,
) -> None:
    """Duplicate pending and muted notification suppression retain current behavior."""
    request = await membership.create_request()
    duplicate = await membership.join_request.request_join(
        user_id=membership.user_id, workspace_handle=membership.handle, message=None
    )
    assert isinstance(duplicate, Failure) and duplicate.error == PendingRequestExists(
        join_request_id=request.id
    )
    assert isinstance(await membership.join_request.mute(request.id), Success)
    requested = await membership.join_request.request_join(
        user_id=membership.user_id, workspace_handle=membership.handle, message="Again"
    )
    assert isinstance(requested, Success)
    assert not requested.value.should_send_notification
    assert requested.value.join_request.id == request.id
    assert requested.value.join_request.message == "Again"
    assert requested.value.join_request.status == JoinRequestStatus.PENDING
    my_request = await membership.join_request.get_my_request(
        user_id=membership.user_id, workspace_handle=membership.handle
    )
    assert isinstance(my_request, Success) and my_request.value is not None
    assert my_request.value.last_notified_at is not None
    listed = await membership.join_request.list_by_workspace(membership.workspace_id)
    assert listed.total == 1 and listed.items[0].id == request.id
    member = await membership.join_request.request_join(
        user_id=membership.owner_id, workspace_handle=membership.handle, message=None
    )
    assert isinstance(member, Failure) and member.error == JoinAlreadyMember(
        user_id=membership.owner_id
    )
    membership.assert_closed()


@pytest.mark.parametrize("action", ["reject", "delete", "approve"])
async def test_join_request_terminal_operations(
    membership: MembershipFixture, action: str
) -> None:
    """Terminal operations preserve membership creation and request removal rules."""
    request = await membership.create_request()
    match action:
        case "reject":
            assert isinstance(await membership.join_request.reject(request.id), Success)
        case "delete":
            await membership.join_request.delete(request.id)
        case "approve":
            approved = await membership.join_request.approve(request.id)
            assert isinstance(approved, Success)
            assert approved.value.user_id == membership.user_id
        case _:
            raise AssertionError(action)
    async with membership.session_manager() as session:
        assert await WorkspaceJoinRequestRepository().get(session, request.id) is None
        member = await WorkspaceUserRepository().get_by_workspace_and_user(
            session, membership.workspace_id, membership.user_id
        )
        if action == "approve":
            assert member is not None and member.role == WorkspaceUserRole.MEMBER
            assert member.name == membership.user_id[:8]
        else:
            assert member is None
    membership.assert_closed()


async def test_join_approval_delete_failure_rolls_back(
    membership: MembershipFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure deleting the request rolls back membership creation."""
    request = await membership.create_request()

    async def fail_delete(session: WriteSession, join_request_id: str) -> None:
        del session, join_request_id
        raise RuntimeError("Injected delete failure")

    monkeypatch.setattr(
        membership.join_request.join_request_repo, "delete", fail_delete
    )
    with pytest.raises(RuntimeError, match="Injected delete"):
        await membership.join_request.approve(request.id)
    membership.assert_closed()
    async with membership.session_manager() as session:
        assert (
            await WorkspaceUserRepository().get_by_workspace_and_user(
                session, membership.workspace_id, membership.user_id
            )
            is None
        )
        assert (
            await WorkspaceJoinRequestRepository().get(session, request.id) is not None
        )


async def test_absent_workspace_and_record_outcomes(
    membership: MembershipFixture,
) -> None:
    """Completed failed reads retain typed not-found outcomes and close transactions."""
    listed = await membership.invitation.list_by_workspace_handle("absent-workspace")
    assert isinstance(listed, Failure) and listed.error == WorkspaceNotFound(
        handle="absent-workspace"
    )
    missing = await membership.invitation.get_my_invitation(
        user_id=membership.user_id, workspace_handle="absent-workspace"
    )
    assert isinstance(missing, Failure)
    assert isinstance(
        await membership.join_request.get_my_request(
            user_id=membership.user_id, workspace_handle="absent-workspace"
        ),
        Failure,
    )
    assert isinstance(
        await membership.join_request.request_join(
            user_id=membership.user_id,
            workspace_handle="absent-workspace",
            message=None,
        ),
        Failure,
    )
    for result in [
        await membership.join_request.approve("absent-request"),
        await membership.join_request.reject("absent-request"),
        await membership.join_request.mute("absent-request"),
    ]:
        assert isinstance(result, Failure) and result.error == JoinRequestNotFound(
            join_request_id="absent-request"
        )
    process = await membership.invitation.process(
        user_id=membership.user_id,
        invitation_id="absent-invitation",
        status=InvitationStatus.ACCEPTED,
    )
    assert isinstance(process, Failure) and process.error == InvitationNotFound(
        invitation_id="absent-invitation"
    )
    my_invitation = await membership.invitation.get_my_invitation(
        user_id=membership.user_id, workspace_handle=membership.handle
    )
    assert isinstance(my_invitation, Success) and my_invitation.value is None
    my_request = await membership.join_request.get_my_request(
        user_id=membership.user_id, workspace_handle=membership.handle
    )
    assert isinstance(my_request, Success) and my_request.value is None
    membership.assert_closed()


@pytest.mark.parametrize("fail_email", [False, True])
async def test_invitation_email_after_commit(
    membership: MembershipFixture, fail_email: bool
) -> None:
    """Normalized invitation remains committed when post-commit delivery fails."""
    email_service = Mock(spec=EmailService)
    email_service.configured = False
    signup = AsyncMock(spec=SignupTokenService)

    async def send(
        *, to_email: str, workspace_name: str, signup_url: str | None
    ) -> None:
        membership.assert_closed()
        assert to_email == membership.email and workspace_name == "Membership"
        assert signup_url is None
        # Independent operation sees the committed invitation before delivery.
        assert (
            await membership.invitation.list_by_workspace(membership.workspace_id)
        ).items[0].email == to_email
        membership.assert_closed()
        if fail_email:
            raise RuntimeError("Injected email failure")

    email_service.send_invitation = AsyncMock(side_effect=send)
    service = WorkspaceInvitationService(
        operation_repo=membership.invitation,
        email_service=require_instance(email_service, EmailService),
        signup_token_service=require_instance(signup, SignupTokenService),
    )
    invitation_input = CreateInvitationInput(
        email=f"  {membership.email.upper()}  ", role=WorkspaceUserRole.MEMBER
    )
    if fail_email:
        with pytest.raises(RuntimeError, match="Injected email"):
            await service.create(membership.member(), invitation_input)
    else:
        assert isinstance(
            await service.create(membership.member(), invitation_input), Success
        )
    signup.create.assert_not_awaited()
    assert (
        len(
            (
                await membership.invitation.list_by_workspace(membership.workspace_id)
            ).items
        )
        == 1
    )
    membership.assert_closed()


@pytest.mark.parametrize("approval", [False, True])
async def test_join_delivery_after_commit(
    membership: MembershipFixture, approval: bool
) -> None:
    """Notification and approval delivery observe committed state and ended scopes."""
    email_service = AsyncMock(spec=EmailService)
    service = WorkspaceJoinRequestService(
        operation_repo=membership.join_request,
        email_service=require_instance(email_service, EmailService),
    )

    async def notify(*, workspace_name: str, workspace_handle: str) -> None:
        membership.assert_closed()
        assert workspace_name == "Membership" and workspace_handle == membership.handle
        request = await membership.join_request.get_my_request(
            user_id=membership.user_id, workspace_handle=membership.handle
        )
        assert isinstance(request, Success) and request.value is not None
        assert request.value.last_notified_at is not None
        membership.assert_closed()
        if not approval:
            raise RuntimeError("Injected notification failure")

    async def approved(*, user_id: str, workspace_name: str) -> None:
        membership.assert_closed()
        assert user_id == membership.user_id and workspace_name == "Membership"
        async with membership.session_manager() as session:
            assert (
                await WorkspaceUserRepository().get_by_workspace_and_user(
                    session, membership.workspace_id, user_id
                )
                is not None
            )
            assert (
                await WorkspaceJoinRequestRepository().get_by_workspace_and_user(
                    session, membership.workspace_id, user_id
                )
                is None
            )
        membership.assert_closed()
        raise RuntimeError("Injected approval email failure")

    email_service.send_join_request_notification.side_effect = notify
    email_service.send_join_request_approved.side_effect = approved
    if approval:
        requested = await service.request_join(membership.user_id, membership.handle)
        assert isinstance(requested, Success)
        with pytest.raises(RuntimeError, match="Injected approval"):
            await service.approve(requested.value.id)
    else:
        with pytest.raises(RuntimeError, match="Injected notification"):
            await service.request_join(membership.user_id, membership.handle)
    membership.assert_closed()


async def test_signup_preparation_after_invitation_commit(
    membership: MembershipFixture,
) -> None:
    """Signup preparation and URL generation observe closed invitation operations."""
    email = f"new-{uuid4().hex}@example.com"
    email_service = Mock(spec=EmailService)
    email_service.configured = True
    signup = Mock(spec=SignupTokenService)
    now = datetime.datetime.now(datetime.UTC)

    async def create_token(
        create: CreateSignupTokenInput,
    ) -> SignupTokenWithPlaintextOutput:
        membership.assert_closed()
        assert create.email == email
        assert create.created_by_user_id == membership.owner_id
        assert create.delivery_method == SignupTokenDeliveryMethod.EMAIL
        assert create.expires_at is None and create.max_uses is None
        listed = await membership.invitation.list_by_workspace(membership.workspace_id)
        assert listed.items[0].email == email
        membership.assert_closed()
        return SignupTokenWithPlaintextOutput(
            token=SignupTokenOutput(
                id="token",
                email=email,
                created_by_user_id=membership.owner_id,
                delivery_method=SignupTokenDeliveryMethod.EMAIL,
                expires_at=now + datetime.timedelta(days=1),
                max_uses=1,
                used_count=0,
                revoked_at=None,
                created_at=now,
                updated_at=now,
            ),
            plaintext_token="test-token",
        )

    def build_url(token: str) -> str:
        membership.assert_closed()
        assert token == "test-token"
        return "https://example.com/signup/test-token"

    async def send(
        *, to_email: str, workspace_name: str, signup_url: str | None
    ) -> None:
        membership.assert_closed()
        assert to_email == email and workspace_name == "Membership"
        assert signup_url == "https://example.com/signup/test-token"

    signup.create = AsyncMock(side_effect=create_token)
    signup.build_signup_url = Mock(side_effect=build_url)
    email_service.send_invitation = AsyncMock(side_effect=send)
    service = WorkspaceInvitationService(
        operation_repo=membership.invitation,
        email_service=require_instance(email_service, EmailService),
        signup_token_service=require_instance(signup, SignupTokenService),
    )
    result = await service.create(
        membership.member(),
        CreateInvitationInput(email=email, role=WorkspaceUserRole.MEMBER),
    )
    assert isinstance(result, Success)
    signup.create.assert_awaited_once()
    email_service.send_invitation.assert_awaited_once()
    membership.assert_closed()


async def test_service_outcome_conversions(membership: MembershipFixture) -> None:
    """Public service outcomes, identities and list projections retain their types."""
    email_service = Mock(spec=EmailService)
    email_service.configured = False
    email_service.send_invitation = AsyncMock()
    email_service.send_join_request_notification = AsyncMock()
    email_service.send_join_request_approved = AsyncMock()
    invitations = WorkspaceInvitationService(
        operation_repo=membership.invitation,
        email_service=require_instance(email_service, EmailService),
        signup_token_service=require_instance(
            Mock(spec=SignupTokenService), SignupTokenService
        ),
    )
    requests = WorkspaceJoinRequestService(
        operation_repo=membership.join_request,
        email_service=require_instance(email_service, EmailService),
    )
    user = CurrentUser(user_id=membership.user_id, session_id="session")
    stranger = CurrentUser(user_id=membership.stranger_id, session_id="session")
    created = await invitations.create(
        membership.member(),
        CreateInvitationInput(email=membership.email, role=WorkspaceUserRole.MEMBER),
    )
    assert isinstance(created, Success)
    invitation_id = created.value.id
    assert (await invitations.list_received(user)).items[0].id == invitation_id
    mine = await invitations.get_my_invitation(user, membership.handle)
    assert isinstance(mine, Success) and mine.value is not None
    assert mine.value.id == invitation_id
    listed = await invitations.list_by_workspace_handle(membership.handle)
    assert isinstance(listed, Success) and listed.value.items[0].id == invitation_id
    assert (await invitations.list_by_workspace(membership.workspace_id)).items[
        0
    ].id == invitation_id
    hidden = await invitations.accept(stranger, invitation_id)
    assert isinstance(hidden, Failure) and isinstance(
        hidden.error, ServiceInvitationNotFound
    )
    declined = await invitations.decline(user, invitation_id)
    assert (
        isinstance(declined, Success)
        and declined.value.status == InvitationStatus.DECLINED
    )
    repeat = await invitations.accept(user, invitation_id)
    assert isinstance(repeat, Failure) and isinstance(
        repeat.error, ServiceAlreadyProcessed
    )
    await invitations.delete(invitation_id)
    requested = await requests.request_join(membership.user_id, membership.handle)
    assert isinstance(requested, Success)
    duplicate = await requests.request_join(membership.user_id, membership.handle)
    assert isinstance(duplicate, Failure) and isinstance(
        duplicate.error, ServicePendingRequestExists
    )
    my_request = await requests.get_my_request(membership.user_id, membership.handle)
    assert isinstance(my_request, Success) and my_request.value is not None
    assert my_request.value.id == requested.value.id
    assert (await requests.list_by_workspace(membership.workspace_id)).items[
        0
    ].id == requested.value.id
    assert isinstance(await requests.mute(requested.value.id), Success)
    email_service.send_join_request_notification.reset_mock()
    assert isinstance(
        await requests.request_join(membership.user_id, membership.handle), Success
    )
    email_service.send_join_request_notification.assert_not_awaited()
    assert isinstance(await requests.approve(requested.value.id), Success)
    already = await requests.request_join(membership.user_id, membership.handle)
    assert isinstance(already, Failure) and isinstance(
        already.error, ServiceJoinAlreadyMember
    )
    duplicate_invitation = await invitations.create(
        membership.member(),
        CreateInvitationInput(email=membership.email, role=WorkspaceUserRole.MEMBER),
    )
    assert isinstance(duplicate_invitation, Failure) and isinstance(
        duplicate_invitation.error, ServiceAlreadyMember
    )
    for result in [
        await requests.approve("absent"),
        await requests.reject("absent"),
        await requests.mute("absent"),
    ]:
        assert isinstance(result, Failure) and isinstance(
            result.error, ServiceJoinRequestNotFound
        )
    await requests.delete("absent")
    membership.assert_closed()


@pytest.mark.parametrize("elapsed_hours", [1, 25])
async def test_join_request_cooldown_preserved_on_upsert_race(
    membership: MembershipFixture,
    monkeypatch: pytest.MonkeyPatch,
    elapsed_hours: int,
) -> None:
    """An upsert discovering a prior record retains the existing cooldown decision."""
    request = await membership.create_request()
    notified_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
        hours=elapsed_hours
    )
    async with membership.session_manager() as session:
        await WorkspaceJoinRequestRepository().update(
            session, request.id, {"last_notified_at": notified_at}
        )

    async def absent_precheck(
        session: WriteSession, workspace_id: str, user_id: str
    ) -> WorkspaceJoinRequest | None:
        del session, workspace_id, user_id
        return None

    monkeypatch.setattr(
        membership.join_request.join_request_repo,
        "get_by_workspace_and_user",
        absent_precheck,
    )
    result = await membership.join_request.request_join(
        user_id=membership.user_id, workspace_handle=membership.handle, message="Race"
    )
    assert isinstance(result, Success)
    assert result.value.should_send_notification == (elapsed_hours > 24)
    async with membership.session_manager() as session:
        stored = await WorkspaceJoinRequestRepository().get(session, request.id)
        assert stored is not None and stored.last_notified_at is not None
        if elapsed_hours > 24:
            assert stored.last_notified_at > notified_at
        else:
            assert stored.last_notified_at == notified_at
    membership.assert_closed()
