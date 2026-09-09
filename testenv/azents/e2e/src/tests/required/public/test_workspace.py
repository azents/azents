"""Public API Workspace test."""

import azentsadminclient
import azentspublicclient
import pytest
from azentsadminclient.api.workspace_v1_api import (
    WorkspaceV1Api as AdminWorkspaceV1Api,
)
from azentsadminclient.models.workspace_create_request import WorkspaceCreateRequest
from azentspublicclient.api.workspace_v1_api import (
    WorkspaceV1Api as PublicWorkspaceV1Api,
)
from azentspublicclient.exceptions import ApiException
from azentspublicclient.models.create_workspace_request import (
    CreateWorkspaceRequest as PublicCreateWorkspaceRequest,
)

from support.utils import authenticate_user, unique


class TestWorkspaceGetByHandle:
    """Test public Workspace lookup by handle."""

    def test_get_workspace_by_handle(
        self,
        admin_api_client: azentsadminclient.ApiClient,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """A Workspace can be fetched by handle."""
        admin_api = AdminWorkspaceV1Api(admin_api_client)
        public_api = PublicWorkspaceV1Api(public_api_client)
        uniq = unique()
        handle = f"ws-public-{uniq}"

        admin_api.workspace_v1_create_workspace(
            WorkspaceCreateRequest(
                name=f"Public Test {uniq}",
                handle=handle,
            )
        )

        fetched = public_api.workspace_v1_get_workspace_by_handle(handle)
        assert fetched.name == f"Public Test {uniq}"
        assert fetched.handle == handle
        assert fetched.created_at is not None
        assert fetched.updated_at is not None

    def test_get_workspace_by_handle_not_found_returns_404(
        self,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """Fetching a nonexistent Workspace handle returns 404."""
        public_api = PublicWorkspaceV1Api(public_api_client)

        with pytest.raises(ApiException) as exc_info:
            public_api.workspace_v1_get_workspace_by_handle("nonexistent-handle")
        assert exc_info.value.status == 404


class TestWorkspaceAuthenticated:
    """Test authenticated Workspace operations."""

    def test_list_workspaces_authenticated(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """An authenticated user can list their Workspaces."""
        uniq = unique()
        access_token, _, _ = authenticate_user(
            public_api_client,
            admin_api_client,
            email=f"ws-list-{uniq}@example.com",
        )

        # Create a Workspace through the Public API.
        public_ws_api = PublicWorkspaceV1Api(public_api_client)
        create_response = public_ws_api.workspace_v1_create_workspace(
            PublicCreateWorkspaceRequest(
                workspace_name=f"WS List {uniq}",
                workspace_handle=f"ws-list-{uniq}",
                owner_name=f"Owner {uniq}",
            ),
            _headers={"Authorization": f"Bearer {access_token}"},
        )

        # Fetch the user's Workspace list.
        response = public_ws_api.workspace_v1_list_workspaces(
            _headers={"Authorization": f"Bearer {access_token}"},
        )
        handles = [ws.handle for ws in response.items]
        assert create_response.workspace_handle in handles

    def test_create_workspace_authenticated(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """An authenticated user can create a Workspace."""
        uniq = unique()
        access_token, _, _ = authenticate_user(
            public_api_client,
            admin_api_client,
        )

        public_ws_api = PublicWorkspaceV1Api(public_api_client)
        response = public_ws_api.workspace_v1_create_workspace(
            PublicCreateWorkspaceRequest(
                workspace_name=f"WS Create {uniq}",
                workspace_handle=f"ws-create-{uniq}",
                owner_name=f"Owner {uniq}",
            ),
            _headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.workspace_handle == f"ws-create-{uniq}"

    def test_list_workspaces_without_token_returns_401(
        self,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """Listing Workspaces without a token returns 401."""
        public_ws_api = PublicWorkspaceV1Api(public_api_client)

        with pytest.raises(ApiException) as exc_info:
            public_ws_api.workspace_v1_list_workspaces()
        assert exc_info.value.status == 401

    def test_create_workspace_without_token_returns_401(
        self,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """Creating a Workspace without a token returns 401."""
        public_ws_api = PublicWorkspaceV1Api(public_api_client)

        with pytest.raises(ApiException) as exc_info:
            public_ws_api.workspace_v1_create_workspace(
                PublicCreateWorkspaceRequest(
                    workspace_name="Test WS",
                    workspace_handle="test-handle",
                    owner_name="Test Owner",
                )
            )
        assert exc_info.value.status == 401
