"""Runtime Profile setup helpers for product E2E journeys."""

import azentspublicclient
from azentspublicclient.api.runtime_profile_v1_api import RuntimeProfileV1Api
from azentspublicclient.models.workspace_runtime_profile_create_request import (
    WorkspaceRuntimeProfileCreateRequest,
)
from azentspublicclient.models.workspace_runtime_profile_policy_v1 import (
    WorkspaceRuntimeProfilePolicyV1,
)

from support.utils import unique


def create_workspace_runtime_profile(
    public_api_client: azentspublicclient.ApiClient,
    *,
    token: str,
    workspace_handle: str,
    provider_id: str,
) -> str:
    """Create and return one exact Workspace Runtime Profile for a Provider."""
    api = RuntimeProfileV1Api(public_api_client)
    headers = {"Authorization": f"Bearer {token}"}
    selectable = api.runtime_profile_v1_list_selectable_infrastructure_profiles(
        handle=workspace_handle,
        _headers=headers,
    )
    candidates = [
        profile for profile in selectable.items if profile.provider_id == provider_id
    ]
    if len(candidates) != 1:
        candidate_ids = [
            (profile.provider_id, profile.id) for profile in selectable.items
        ]
        raise AssertionError(
            "expected exactly one selectable infrastructure Profile for "
            f"{provider_id!r}, found {candidate_ids!r}"
        )
    suffix = unique()
    profile = api.runtime_profile_v1_create_workspace_runtime_profile(
        handle=workspace_handle,
        workspace_runtime_profile_create_request=WorkspaceRuntimeProfileCreateRequest(
            infrastructure_profile_id=candidates[0].id,
            display_name=f"E2E Runtime {suffix}",
            description="Exact Runtime Profile for a Runtime Provider E2E journey.",
            policy=WorkspaceRuntimeProfilePolicyV1(
                schema_version=1,
                network_restriction=None,
            ),
        ),
        _headers=headers,
    )
    if profile.provider_id != provider_id or not profile.available:
        raise AssertionError(
            "created Workspace Runtime Profile is not selectable: "
            f"provider={profile.provider_id!r}, available={profile.available!r}, "
            f"reason={profile.availability_reason_code!r}"
        )
    return profile.id
