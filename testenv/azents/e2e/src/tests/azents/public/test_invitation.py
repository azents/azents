"""Public API Invitation test."""

import azentsadminclient
import azentspublicclient
import pytest
from azentsadminclient.api.invitation_v1_api import (
    InvitationV1Api as AdminInvitationV1Api,
)
from azentspublicclient.api.invitation_v1_api import InvitationV1Api
from azentspublicclient.api.workspace_user_v1_api import WorkspaceUserV1Api
from azentspublicclient.api.workspace_v1_api import (
    WorkspaceV1Api as PublicWorkspaceV1Api,
)
from azentspublicclient.exceptions import ApiException
from azentspublicclient.models.create_invitation_request import (
    CreateInvitationRequest,
)
from azentspublicclient.models.create_workspace_request import (
    CreateWorkspaceRequest as PublicCreateWorkspaceRequest,
)
from azentspublicclient.models.update_workspace_user_role_request import (
    UpdateWorkspaceUserRoleRequest,
)
from azentspublicclient.models.workspace_user_role import WorkspaceUserRole

from support.utils import authenticate_user, unique


def _setup_workspace_with_owner(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
) -> tuple[str, str, str]:
    """workspace create + owner t t.

    :return: (access_token, email, workspace_handle) t
    """
    uniq = unique()
    email = f"owner-{uniq}@example.com"
    access_token, _, email = authenticate_user(
        public_api_client, admin_api_client, email=email
    )

    public_ws_api = PublicWorkspaceV1Api(public_api_client)
    handle = f"ws-{uniq}"
    public_ws_api.workspace_v1_create_workspace(
        PublicCreateWorkspaceRequest(
            workspace_name=f"Workspace {uniq}",
            workspace_handle=handle,
            owner_name=f"Owner {uniq}",
        ),
        _headers={"Authorization": f"Bearer {access_token}"},
    )

    return access_token, email, handle


class TestCreateInvitation:
    """invitation create t test."""

    def test_create_invitation_success(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """invitationt t createt."""
        access_token, _, handle = _setup_workspace_with_owner(
            public_api_client, admin_api_client
        )
        inv_api = InvitationV1Api(public_api_client)

        result = inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(email="newinvitee@example.com"),
            _headers={"Authorization": f"Bearer {access_token}"},
        )

        assert result.id is not None
        assert result.email == "newinvitee@example.com"
        assert result.status == "pending"

    def test_create_invitation_with_role(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """manager rolet invitationt createt."""
        access_token, _, handle = _setup_workspace_with_owner(
            public_api_client, admin_api_client
        )
        inv_api = InvitationV1Api(public_api_client)

        result = inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(
                email="manager-invitee@example.com", role=WorkspaceUserRole.MANAGER
            ),
            _headers={"Authorization": f"Bearer {access_token}"},
        )

        assert result.role == WorkspaceUserRole.MANAGER

    def test_create_invitation_without_token_returns_401(
        self,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """token t invitation create t 401t returnt."""
        inv_api = InvitationV1Api(public_api_client)

        with pytest.raises(ApiException) as exc_info:
            inv_api.invitation_v1_create_invitation(
                "any-handle",
                CreateInvitationRequest(email="test@example.com"),
            )
        assert exc_info.value.status == 401  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t

    def test_reinvite_after_decline(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """rejectt invitationt t t pendingt t."""
        owner_token, _, handle = _setup_workspace_with_owner(
            public_api_client, admin_api_client
        )
        inv_api = InvitationV1Api(public_api_client)

        # invitation t t create
        uniq = unique()
        invitee_email = f"reinv-{uniq}@example.com"
        invitee_token, _, _ = authenticate_user(
            public_api_client, admin_api_client, email=invitee_email
        )

        # invitation create
        created = inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(email=invitee_email),
            _headers={"Authorization": f"Bearer {owner_token}"},
        )

        # invitation reject
        inv_api.invitation_v1_decline_invitation(
            created.id,
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )

        # tinvitation
        reinvited = inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(email=invitee_email),
            _headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert reinvited.status == "pending"
        assert reinvited.id == created.id

    def test_resend_pending_invitation(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """pending state invitationt t t t t processt."""
        access_token, _, handle = _setup_workspace_with_owner(
            public_api_client, admin_api_client
        )
        inv_api = InvitationV1Api(public_api_client)

        email = f"resend-{unique()}@example.com"

        # t t invitation
        first = inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(email=email),
            _headers={"Authorization": f"Bearer {access_token}"},
        )

        # t emailt t invitation (t)
        second = inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(email=email),
            _headers={"Authorization": f"Bearer {access_token}"},
        )

        assert second.id == first.id
        assert second.status == "pending"


class TestListReceivedInvitations:
    """t invitation list fetch test."""

    def test_list_received_invitations_empty(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """invitationt t t listt returnt."""
        access_token, _, _ = authenticate_user(public_api_client, admin_api_client)
        inv_api = InvitationV1Api(public_api_client)

        result = inv_api.invitation_v1_list_received_invitations(
            _headers={"Authorization": f"Bearer {access_token}"},
        )
        assert result.items == []

    def test_list_received_invitations_without_token_returns_401(
        self,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """token t t invitation fetch t 401t returnt."""
        inv_api = InvitationV1Api(public_api_client)

        with pytest.raises(ApiException) as exc_info:
            inv_api.invitation_v1_list_received_invitations()
        assert exc_info.value.status == 401  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t

    def test_list_received_invitations_shows_pending(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """pending state invitationt t invitation listt t."""
        owner_token, _, handle = _setup_workspace_with_owner(
            public_api_client, admin_api_client
        )
        inv_api = InvitationV1Api(public_api_client)

        # invitation t t create
        uniq = unique()
        invitee_email = f"recv-{uniq}@example.com"
        invitee_token, _, _ = authenticate_user(
            public_api_client, admin_api_client, email=invitee_email
        )

        # invitation create
        inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(email=invitee_email),
            _headers={"Authorization": f"Bearer {owner_token}"},
        )

        # invitation t t invitation fetch
        result = inv_api.invitation_v1_list_received_invitations(
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )

        assert len(result.items) >= 1
        invitation = next(i for i in result.items if i.email == invitee_email)
        assert invitation.workspace_handle == handle
        assert invitation.status == "pending"


class TestAcceptInvitation:
    """invitation t test."""

    def test_accept_invitation_success(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """invitationt t workspace membert t."""
        owner_token, _, handle = _setup_workspace_with_owner(
            public_api_client, admin_api_client
        )
        inv_api = InvitationV1Api(public_api_client)
        public_ws_api = PublicWorkspaceV1Api(public_api_client)

        # invitation t t create
        uniq = unique()
        invitee_email = f"accept-{uniq}@example.com"
        invitee_token, _, _ = authenticate_user(
            public_api_client, admin_api_client, email=invitee_email
        )

        # invitation create
        created = inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(email=invitee_email),
            _headers={"Authorization": f"Bearer {owner_token}"},
        )

        # invitation t
        accepted = inv_api.invitation_v1_accept_invitation(
            created.id,
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )
        assert accepted.status == "accepted"

        # t t workspace listt t
        ws_list = public_ws_api.workspace_v1_list_workspaces(
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )
        assert any(ws.handle == handle for ws in ws_list.items)

    def test_accept_invitation_not_found_returns_404(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """existst t invitation t t 404t returnt."""
        access_token, _, _ = authenticate_user(public_api_client, admin_api_client)
        inv_api = InvitationV1Api(public_api_client)

        with pytest.raises(ApiException) as exc_info:
            inv_api.invitation_v1_accept_invitation(
                "nonexistent_id_12345678",
                _headers={"Authorization": f"Bearer {access_token}"},
            )
        assert exc_info.value.status == 404  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t

    def test_accept_other_users_invitation_returns_404(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """t t invitationt t t 404t returnt (security)."""
        owner_token, _, handle = _setup_workspace_with_owner(
            public_api_client, admin_api_client
        )
        inv_api = InvitationV1Api(public_api_client)

        # invitation t t
        uniq = unique()
        invitee_email = f"target-{uniq}@example.com"
        authenticate_user(public_api_client, admin_api_client, email=invitee_email)

        # invitation create
        created = inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(email=invitee_email),
            _headers={"Authorization": f"Bearer {owner_token}"},
        )

        # t t t t
        other_token, _, _ = authenticate_user(
            public_api_client, admin_api_client, email=f"other-{uniq}@example.com"
        )

        with pytest.raises(ApiException) as exc_info:
            inv_api.invitation_v1_accept_invitation(
                created.id,
                _headers={"Authorization": f"Bearer {other_token}"},
            )
        assert exc_info.value.status == 404  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t


class TestDeclineInvitation:
    """invitation reject test."""

    def test_decline_invitation_success(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """invitationt rejectt."""
        owner_token, _, handle = _setup_workspace_with_owner(
            public_api_client, admin_api_client
        )
        inv_api = InvitationV1Api(public_api_client)

        # invitation t t create
        uniq = unique()
        invitee_email = f"decline-{uniq}@example.com"
        invitee_token, _, _ = authenticate_user(
            public_api_client, admin_api_client, email=invitee_email
        )

        # invitation create + reject
        created = inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(email=invitee_email),
            _headers={"Authorization": f"Bearer {owner_token}"},
        )

        declined = inv_api.invitation_v1_decline_invitation(
            created.id,
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )
        assert declined.status == "declined"

        # reject t t invitation listt t t
        received = inv_api.invitation_v1_list_received_invitations(
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )
        assert all(i.id != created.id for i in received.items)

    def test_decline_other_users_invitation_returns_404(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """t t invitationt rejectt t 404t returnt (security)."""
        owner_token, _, handle = _setup_workspace_with_owner(
            public_api_client, admin_api_client
        )
        inv_api = InvitationV1Api(public_api_client)

        # invitation t t
        uniq = unique()
        invitee_email = f"dtarget-{uniq}@example.com"
        authenticate_user(public_api_client, admin_api_client, email=invitee_email)

        created = inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(email=invitee_email),
            _headers={"Authorization": f"Bearer {owner_token}"},
        )

        # t t reject t
        other_token, _, _ = authenticate_user(
            public_api_client, admin_api_client, email=f"dother-{uniq}@example.com"
        )

        with pytest.raises(ApiException) as exc_info:
            inv_api.invitation_v1_decline_invitation(
                created.id,
                _headers={"Authorization": f"Bearer {other_token}"},
            )
        assert exc_info.value.status == 404  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t


class TestInvitationFullFlow:
    """invitation t t integration test."""

    def test_invitation_for_missing_user_survives_signup_token_registration(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """t t invitation t t email join t pending invitationt t t."""
        owner_token, _, handle = _setup_workspace_with_owner(
            public_api_client, admin_api_client
        )
        inv_api = InvitationV1Api(public_api_client)
        public_ws_api = PublicWorkspaceV1Api(public_api_client)
        uniq = unique()
        invitee_email = f"missing-{uniq}@example.com"

        created = inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(
                email=invitee_email, role=WorkspaceUserRole.MANAGER
            ),
            _headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert created.status == "pending"

        invitee_token, _, _ = authenticate_user(
            public_api_client, admin_api_client, email=invitee_email
        )

        received = inv_api.invitation_v1_list_received_invitations(
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )
        pending = [i for i in received.items if i.id == created.id]
        assert len(pending) == 1
        assert pending[0].workspace_handle == handle

        accepted = inv_api.invitation_v1_accept_invitation(
            created.id,
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )
        assert accepted.status == "accepted"

        ws_list = public_ws_api.workspace_v1_list_workspaces(
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )
        assert any(ws.handle == handle for ws in ws_list.items)

    def test_full_invitation_flow(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """invitation create → t check → t → workspace member check t t."""
        owner_token, _, handle = _setup_workspace_with_owner(
            public_api_client, admin_api_client
        )
        inv_api = InvitationV1Api(public_api_client)
        admin_inv_api = AdminInvitationV1Api(admin_api_client)
        public_ws_api = PublicWorkspaceV1Api(public_api_client)

        # invitation t t
        uniq = unique()
        invitee_email = f"flow-{uniq}@example.com"
        invitee_token, _, _ = authenticate_user(
            public_api_client, admin_api_client, email=invitee_email
        )

        # 1. invitation create
        created = inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(
                email=invitee_email, role=WorkspaceUserRole.MANAGER
            ),
            _headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert created.status == "pending"
        assert created.role == WorkspaceUserRole.MANAGER

        # 2. Admin APIt invitation check
        admin_list = admin_inv_api.invitation_v1_list_workspace_invitations(handle)
        assert any(i.id == created.id for i in admin_list.items)

        # 3. invitation t t t invitation list check
        received = inv_api.invitation_v1_list_received_invitations(
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )
        pending = [i for i in received.items if i.id == created.id]
        assert len(pending) == 1
        assert pending[0].workspace_handle == handle

        # 4. invitation t
        accepted = inv_api.invitation_v1_accept_invitation(
            created.id,
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )
        assert accepted.status == "accepted"

        # 5. workspace member check
        ws_list = public_ws_api.workspace_v1_list_workspaces(
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )
        assert any(ws.handle == handle for ws in ws_list.items)

        # 6. t t t invitation listt t
        received_after = inv_api.invitation_v1_list_received_invitations(
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )
        assert all(i.id != created.id for i in received_after.items)


class TestReinviteAfterRemoval:
    """member t t tinvitation test."""

    def test_owner_can_update_existing_member_role(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """t workspace member role t owner t t."""
        owner_token, _, handle = _setup_workspace_with_owner(
            public_api_client, admin_api_client
        )
        inv_api = InvitationV1Api(public_api_client)
        ws_user_api = WorkspaceUserV1Api(public_api_client)

        uniq = unique()
        invitee_email = f"role-update-{uniq}@example.com"
        invitee_token, _, _ = authenticate_user(
            public_api_client, admin_api_client, email=invitee_email
        )

        invitation = inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(email=invitee_email),
            _headers={"Authorization": f"Bearer {owner_token}"},
        )
        inv_api.invitation_v1_accept_invitation(
            invitation.id,
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )

        members = ws_user_api.workspaceuser_v1_list_workspace_users(
            handle,
            _headers={"Authorization": f"Bearer {owner_token}"},
        )
        invitee = next(
            member
            for member in members.items
            if member.name == invitee_email.split("@", maxsplit=1)[0]
        )

        ws_user_api.workspaceuser_v1_update_workspace_user_role(
            handle=handle,
            workspace_user_id=invitee.id,
            update_workspace_user_role_request=UpdateWorkspaceUserRoleRequest(
                role=WorkspaceUserRole.MANAGER,
            ),
            _headers={"Authorization": f"Bearer {owner_token}"},
        )

        updated_members = ws_user_api.workspaceuser_v1_list_workspace_users(
            handle,
            _headers={"Authorization": f"Bearer {owner_token}"},
        )
        updated_invitee = next(
            member for member in updated_members.items if member.id == invitee.id
        )
        assert updated_invitee.role == WorkspaceUserRole.MANAGER

    def test_reinvite_after_removal(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """invitation t → member t → tinvitation → t t t."""
        owner_token, _, handle = _setup_workspace_with_owner(
            public_api_client, admin_api_client
        )
        inv_api = InvitationV1Api(public_api_client)
        ws_user_api = WorkspaceUserV1Api(public_api_client)
        public_ws_api = PublicWorkspaceV1Api(public_api_client)

        # invitation t t create
        uniq = unique()
        invitee_email = f"reinv-rm-{uniq}@example.com"
        invitee_token, _, _ = authenticate_user(
            public_api_client, admin_api_client, email=invitee_email
        )

        # 1. invitation create
        created = inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(email=invitee_email),
            _headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert created.status == "pending"

        # 2. invitation t
        inv_api.invitation_v1_accept_invitation(
            created.id,
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )

        # 3. member listt inviteet workspace_user_id fetch
        members = ws_user_api.workspaceuser_v1_list_workspace_users(
            handle,
            _headers={"Authorization": f"Bearer {owner_token}"},
        )
        invitee_wu = next(
            m
            for m in members.items
            if m.name == invitee_email.split("@", maxsplit=1)[0]
        )

        # 4. member t (delete)
        ws_user_api.workspaceuser_v1_delete_workspace_user(
            invitee_wu.id,
            handle,
            _headers={"Authorization": f"Bearer {owner_token}"},
        )

        # 5. t t workspacet t check
        ws_list = public_ws_api.workspace_v1_list_workspaces(
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )
        assert all(ws.handle != handle for ws in ws_list.items)

        # 6. tinvitation (previoust t 409 t t)
        reinvited = inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(email=invitee_email),
            _headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert reinvited.status == "pending"
        assert reinvited.id == created.id

        # 7. tinvitation t
        accepted = inv_api.invitation_v1_accept_invitation(
            reinvited.id,
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )
        assert accepted.status == "accepted"

        # 8. t workspace membert t
        ws_list_after = public_ws_api.workspace_v1_list_workspaces(
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )
        assert any(ws.handle == handle for ws in ws_list_after.items)

    def test_reinvite_after_removal_with_different_role(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """t t t rolet tinvitationt t rolet t."""
        owner_token, _, handle = _setup_workspace_with_owner(
            public_api_client, admin_api_client
        )
        inv_api = InvitationV1Api(public_api_client)
        ws_user_api = WorkspaceUserV1Api(public_api_client)

        # invitation t t create
        uniq = unique()
        invitee_email = f"role-{uniq}@example.com"
        invitee_token, _, _ = authenticate_user(
            public_api_client, admin_api_client, email=invitee_email
        )

        # 1. member rolet invitation + t
        created = inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(email=invitee_email, role=WorkspaceUserRole.MEMBER),
            _headers={"Authorization": f"Bearer {owner_token}"},
        )
        inv_api.invitation_v1_accept_invitation(
            created.id,
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )

        # 2. member t
        members = ws_user_api.workspaceuser_v1_list_workspace_users(
            handle,
            _headers={"Authorization": f"Bearer {owner_token}"},
        )
        invitee_wu = next(
            m
            for m in members.items
            if m.name == invitee_email.split("@", maxsplit=1)[0]
        )
        ws_user_api.workspaceuser_v1_delete_workspace_user(
            invitee_wu.id,
            handle,
            _headers={"Authorization": f"Bearer {owner_token}"},
        )

        # 3. manager rolet tinvitation
        reinvited = inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(
                email=invitee_email, role=WorkspaceUserRole.MANAGER
            ),
            _headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert reinvited.status == "pending"
        assert reinvited.role == WorkspaceUserRole.MANAGER

        # 4. tinvitation t t t role check
        inv_api.invitation_v1_accept_invitation(
            reinvited.id,
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )
        members_after = ws_user_api.workspaceuser_v1_list_workspace_users(
            handle,
            _headers={"Authorization": f"Bearer {owner_token}"},
        )
        reinvited_member = next(
            m
            for m in members_after.items
            if m.name == invitee_email.split("@", maxsplit=1)[0]
        )
        assert reinvited_member.role == WorkspaceUserRole.MANAGER

    def test_reinvite_after_removal_shows_in_received(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """t t tinvitationt t invitation listt t."""
        owner_token, _, handle = _setup_workspace_with_owner(
            public_api_client, admin_api_client
        )
        inv_api = InvitationV1Api(public_api_client)
        ws_user_api = WorkspaceUserV1Api(public_api_client)

        # invitation t t create
        uniq = unique()
        invitee_email = f"recv-rm-{uniq}@example.com"
        invitee_token, _, _ = authenticate_user(
            public_api_client, admin_api_client, email=invitee_email
        )

        # 1. invitation + t + t
        created = inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(email=invitee_email),
            _headers={"Authorization": f"Bearer {owner_token}"},
        )
        inv_api.invitation_v1_accept_invitation(
            created.id,
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )
        members = ws_user_api.workspaceuser_v1_list_workspace_users(
            handle,
            _headers={"Authorization": f"Bearer {owner_token}"},
        )
        invitee_wu = next(
            m
            for m in members.items
            if m.name == invitee_email.split("@", maxsplit=1)[0]
        )
        ws_user_api.workspaceuser_v1_delete_workspace_user(
            invitee_wu.id,
            handle,
            _headers={"Authorization": f"Bearer {owner_token}"},
        )

        # 2. tinvitation
        inv_api.invitation_v1_create_invitation(
            handle,
            CreateInvitationRequest(email=invitee_email),
            _headers={"Authorization": f"Bearer {owner_token}"},
        )

        # 3. t invitation listt pending statet t t
        received = inv_api.invitation_v1_list_received_invitations(
            _headers={"Authorization": f"Bearer {invitee_token}"},
        )
        matching = [i for i in received.items if i.email == invitee_email]
        assert len(matching) == 1
        assert matching[0].status == "pending"
        assert matching[0].workspace_handle == handle
