"""Admin API Workspace CRUD test."""

import uuid

import azentsadminclient
import pytest
from azentsadminclient.api.workspace_v1_api import WorkspaceV1Api
from azentsadminclient.exceptions import ApiException
from azentsadminclient.models.workspace_create_request import WorkspaceCreateRequest
from azentsadminclient.models.workspace_update_request import WorkspaceUpdateRequest


class TestWorkspaceCrud:
    """Workspace CRUD t test."""

    def test_create_get_update_delete_workspace(
        self,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Workspace create/fetch/update/deletet t t."""
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

        api.workspace_v1_delete_workspace(created.handle)

        with pytest.raises(ApiException) as exc_info:
            api.workspace_v1_get_workspace(created.handle)
        assert exc_info.value.status == 404  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t

    def test_create_workspace_with_duplicate_handle_returns_409(
        self,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """t handlet createt 409t returnt."""
        api = WorkspaceV1Api(admin_api_client)
        unique = uuid.uuid4().hex[:8]
        handle = f"duplicate-handle-{unique}"

        first = api.workspace_v1_create_workspace(
            WorkspaceCreateRequest(name="First", handle=handle)
        )

        try:
            with pytest.raises(ApiException) as exc_info:
                api.workspace_v1_create_workspace(
                    WorkspaceCreateRequest(name="Second", handle=handle)
                )
            assert exc_info.value.status == 409  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t
        finally:
            api.workspace_v1_delete_workspace(first.handle)

    def test_list_workspaces_includes_created_workspace(
        self,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """list fetcht createt Workspacet t."""
        api = WorkspaceV1Api(admin_api_client)
        unique = uuid.uuid4().hex[:8]

        created = api.workspace_v1_create_workspace(
            WorkspaceCreateRequest(
                name=f"Workspace List {unique}",
                handle=f"workspace-list-{unique}",
            )
        )

        try:
            listed = api.workspace_v1_list_workspaces()
            assert any(item.handle == created.handle for item in listed.items)
        finally:
            api.workspace_v1_delete_workspace(created.handle)


class TestWorkspaceValidation:
    """Workspace verify t test."""

    @pytest.mark.parametrize("handle", ["invalid-handle-nonexist", "zz-nonexist-00"])
    def test_get_workspace_not_found_returns_404(
        self,
        admin_api_client: azentsadminclient.ApiClient,
        handle: str,
    ) -> None:
        """existst t Workspace fetch t 404t returnt."""
        api = WorkspaceV1Api(admin_api_client)
        with pytest.raises(ApiException) as exc_info:
            api.workspace_v1_get_workspace(handle)
        assert exc_info.value.status == 404  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t
