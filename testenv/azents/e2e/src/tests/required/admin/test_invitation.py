"""Admin API Invitation test."""

import azentsadminclient
import azentspublicclient
from azentsadminclient.api.invitation_v1_api import InvitationV1Api
from azentspublicclient.api.invitation_v1_api import (
    InvitationV1Api as PublicInvitationV1Api,
)
from azentspublicclient.api.workspace_v1_api import (
    WorkspaceV1Api as PublicWorkspaceV1Api,
)
from azentspublicclient.models.create_invitation_request import (
    CreateInvitationRequest,
)
from azentspublicclient.models.create_workspace_request import (
    CreateWorkspaceRequest as PublicCreateWorkspaceRequest,
)

from support.utils import authenticate_user, unique


class TestAdminInvitation:
    """Admin API invitation fetch/delete test."""

    def test_list_workspace_invitations(
        self,
        admin_api_client: azentsadminclient.ApiClient,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """workspace invitation listt fetcht."""
        uniq = unique()

        # t create + workspace create (owner/manager permission t)
        access_token, _, _ = authenticate_user(
            public_api_client, admin_api_client, email=f"inv-admin-{uniq}@example.com"
        )
        public_ws_api = PublicWorkspaceV1Api(public_api_client)
        public_ws_api.workspace_v1_create_workspace(
            PublicCreateWorkspaceRequest(
                workspace_name=f"WS {uniq}",
                workspace_handle=f"ws-inv-{uniq}",
                owner_name=f"Owner {uniq}",
            ),
            _headers={"Authorization": f"Bearer {access_token}"},
        )

        # invitation create
        public_inv_api = PublicInvitationV1Api(public_api_client)
        public_inv_api.invitation_v1_create_invitation(
            f"ws-inv-{uniq}",
            CreateInvitationRequest(email=f"invitee-{uniq}@example.com"),
            _headers={"Authorization": f"Bearer {access_token}"},
        )

        # Admin APIt invitation list fetch
        admin_inv_api = InvitationV1Api(admin_api_client)
        result = admin_inv_api.invitation_v1_list_workspace_invitations(
            f"ws-inv-{uniq}"
        )
        assert len(result.items) == 1
        assert result.items[0].email == f"invitee-{uniq}@example.com"
        assert result.items[0].status == "pending"

    def test_delete_invitation(
        self,
        admin_api_client: azentsadminclient.ApiClient,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """invitationt delete(cancel)t."""
        uniq = unique()

        # workspace + invitation create
        access_token, _, _ = authenticate_user(
            public_api_client, admin_api_client, email=f"inv-del-{uniq}@example.com"
        )
        public_ws_api = PublicWorkspaceV1Api(public_api_client)
        public_ws_api.workspace_v1_create_workspace(
            PublicCreateWorkspaceRequest(
                workspace_name=f"WS Del {uniq}",
                workspace_handle=f"ws-del-{uniq}",
                owner_name=f"Owner {uniq}",
            ),
            _headers={"Authorization": f"Bearer {access_token}"},
        )

        public_inv_api = PublicInvitationV1Api(public_api_client)
        created = public_inv_api.invitation_v1_create_invitation(
            f"ws-del-{uniq}",
            CreateInvitationRequest(email=f"del-target-{uniq}@example.com"),
            _headers={"Authorization": f"Bearer {access_token}"},
        )

        # Admin APIt delete
        admin_inv_api = InvitationV1Api(admin_api_client)
        admin_inv_api.invitation_v1_delete_invitation(created.id)

        # delete check - listt t
        result = admin_inv_api.invitation_v1_list_workspace_invitations(
            f"ws-del-{uniq}"
        )
        assert len(result.items) == 0

    def test_delete_nonexistent_invitation_is_idempotent(
        self,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """existst t invitation delete t 204t returnt (t)."""
        admin_inv_api = InvitationV1Api(admin_api_client)

        # existst t ID delete t exception t success (204)
        admin_inv_api.invitation_v1_delete_invitation("nonexistent_id_12345678")
