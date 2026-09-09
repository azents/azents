"""Admin API Workspace CRUD test."""

import uuid

import azentsadminclient
import pytest
from azentsadminclient.api.workspace_v1_api import WorkspaceV1Api
from azentsadminclient.exceptions import ApiException
from azentsadminclient.models.workspace_create_request import WorkspaceCreateRequest
from azentsadminclient.models.workspace_update_request import WorkspaceUpdateRequest


class TestWorkspaceCrud:
    """Test Workspace CRUD operations."""

    def test_create_get_update_workspace(
        self,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Workspace create/fetch/update."""
        api = WorkspaceV1Api(admin_api_client)
        unique = uuid.uuid4().hex[:8]

        created = api.workspace_v1_create_workspace(
            WorkspaceCreateRequest(
                name=f"Workspace {unique}",
                handle=f"workspace-{unique}",
            )
        )

        fetched = api.workspace_v1_get_workspace(created.handle)
        assert fetched.handle == f"workspace-{unique}"

        updated = api.workspace_v1_update_workspace(
            created.handle,
            WorkspaceUpdateRequest(name=f"Workspace Updated {unique}"),
        )
        assert updated.name == f"Workspace Updated {unique}"

    def test_create_workspace_with_duplicate_handle_returns_409(
        self,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Creating a duplicate Workspace handle returns 409."""
        api = WorkspaceV1Api(admin_api_client)
        unique = uuid.uuid4().hex[:8]
        handle = f"duplicate-handle-{unique}"

        api.workspace_v1_create_workspace(
            WorkspaceCreateRequest(name="First", handle=handle)
        )

        with pytest.raises(ApiException) as exc_info:
            api.workspace_v1_create_workspace(
                WorkspaceCreateRequest(name="Second", handle=handle)
            )
        assert exc_info.value.status == 409

    def test_list_workspaces_includes_created_workspace(
        self,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """The Workspace list includes a newly created Workspace."""
        api = WorkspaceV1Api(admin_api_client)
        unique = uuid.uuid4().hex[:8]

        created = api.workspace_v1_create_workspace(
            WorkspaceCreateRequest(
                name=f"Workspace List {unique}",
                handle=f"workspace-list-{unique}",
            )
        )

        listed = api.workspace_v1_list_workspaces()
        assert any(item.handle == created.handle for item in listed.items)


class TestWorkspaceValidation:
    """Test Workspace validation."""

    @pytest.mark.parametrize("handle", ["invalid-handle-nonexist", "zz-nonexist-00"])
    def test_get_workspace_not_found_returns_404(
        self,
        admin_api_client: azentsadminclient.ApiClient,
        handle: str,
    ) -> None:
        """Fetching a nonexistent Workspace returns 404."""
        api = WorkspaceV1Api(admin_api_client)
        with pytest.raises(ApiException) as exc_info:
            api.workspace_v1_get_workspace(handle)
        assert exc_info.value.status == 404
