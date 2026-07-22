"""Public API member profile update test.

workspace membert t profile(t, t)t fetch/updatet t verifyt.
"""

from typing import Any

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.workspace_v1_api import (
    WorkspaceV1Api as PublicWorkspaceV1Api,
)
from azentspublicclient.models.create_workspace_request import (
    CreateWorkspaceRequest as PublicCreateWorkspaceRequest,
)

from support.utils import authenticate_user, unique


def _setup_workspace(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
) -> tuple[str, str, str]:
    """testt workspacet createt (access_token, handle, owner_name)t return."""
    uniq = unique()
    access_token, _, _ = authenticate_user(public_api_client, admin_api_client)

    public_ws_api = PublicWorkspaceV1Api(public_api_client)
    handle = f"ws-profile-{uniq}"
    owner_name = f"Owner {uniq}"

    public_ws_api.workspace_v1_create_workspace(
        PublicCreateWorkspaceRequest(
            workspace_name=f"Profile Test {uniq}",
            workspace_handle=handle,
            owner_name=owner_name,
        ),
        _headers={"Authorization": f"Bearer {access_token}"},
    )

    return access_token, handle, owner_name


def _get_my_profile(
    public_api_client: azentspublicclient.ApiClient,
    access_token: str,
    handle: str,
) -> dict[str, Any]:
    """member profilet fetcht (raw HTTP use)."""
    base_url = f"{public_api_client.configuration.host}"  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t
    response = requests.get(
        f"{base_url}/workspace-user/v1/workspaces/{handle}/me/profile",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def _update_my_profile(
    public_api_client: azentspublicclient.ApiClient,
    access_token: str,
    handle: str,
    *,
    name: str | None = None,
) -> dict[str, Any]:
    """member profilet updatet (raw HTTP use)."""
    base_url = f"{public_api_client.configuration.host}"  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t
    body: dict[str, str] = {}
    if name is not None:
        body["name"] = name

    response = requests.patch(
        f"{base_url}/workspace-user/v1/workspaces/{handle}/me/profile",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


class TestGetMyProfile:
    """t workspace profile fetch test."""

    def test_get_my_profile(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """workspace membert t profilet fetcht t t."""
        access_token, handle, owner_name = _setup_workspace(
            public_api_client, admin_api_client
        )

        profile = _get_my_profile(public_api_client, access_token, handle)

        assert profile["name"] == owner_name
        assert "locale" not in profile
        assert profile["role"] == "owner"
        assert profile["id"] is not None
        assert profile["created_at"] is not None
        assert profile["updated_at"] is not None

    def test_get_my_profile_without_token_returns_401(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """token t profile fetch t 401t returnt."""
        base_url = f"{public_api_client.configuration.host}"  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t
        response = requests.get(
            f"{base_url}/workspace-user/v1/workspaces/any-handle/me/profile",
            timeout=10,
        )
        assert response.status_code == 401


class TestUpdateMyProfile:
    """t workspace profile update test."""

    def test_update_name(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """t t t t."""
        access_token, handle, _ = _setup_workspace(public_api_client, admin_api_client)

        updated = _update_my_profile(
            public_api_client, access_token, handle, name="New Name"
        )
        assert updated["name"] == "New Name"

        # fetcht t check
        profile = _get_my_profile(public_api_client, access_token, handle)
        assert profile["name"] == "New Name"

    def test_update_without_token_returns_401(
        self,
        public_api_client: azentspublicclient.ApiClient,
    ) -> None:
        """token t profile update t 401t returnt."""
        base_url = f"{public_api_client.configuration.host}"  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t
        response = requests.patch(
            f"{base_url}/workspace-user/v1/workspaces/any-handle/me/profile",
            json={"name": "Test"},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        assert response.status_code == 401

    def test_update_empty_body_returns_current_profile(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """t bodyt update t current profilet t returnt."""
        access_token, handle, owner_name = _setup_workspace(
            public_api_client, admin_api_client
        )

        updated = _update_my_profile(public_api_client, access_token, handle)
        assert updated["name"] == owner_name
        assert "locale" not in updated

    def test_update_preserves_role(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """profile update t rolet t t."""
        access_token, handle, _ = _setup_workspace(public_api_client, admin_api_client)

        updated = _update_my_profile(
            public_api_client, access_token, handle, name="Changed"
        )
        assert updated["role"] == "owner"
