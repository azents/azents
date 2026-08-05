"""Runtime Profile setup helpers for product E2E journeys."""

import time
import uuid

import azentspublicclient
from azentspublicclient.api.agent_runtime_v1_api import AgentRuntimeV1Api
from azentspublicclient.api.runtime_profile_v1_api import RuntimeProfileV1Api
from azentspublicclient.models.workspace_runtime_profile_create_request import (
    WorkspaceRuntimeProfileCreateRequest,
)
from azentspublicclient.models.workspace_runtime_profile_policy_v1 import (
    WorkspaceRuntimeProfilePolicyV1,
)

_RUNTIME_READY_TIMEOUT_SECONDS = 120


def _unique() -> str:
    """Return a short unique suffix without importing general test helpers."""
    return uuid.uuid4().hex[:8]


def start_and_wait_for_agent_runtime(
    public_api_client: azentspublicclient.ApiClient,
    *,
    token: str,
    workspace_handle: str,
    agent_id: str,
) -> None:
    """Start an Agent Runtime and wait for Runner workspace evidence."""
    api = AgentRuntimeV1Api(public_api_client)
    headers = {"Authorization": f"Bearer {token}"}
    api.agent_runtime_v1_start_agent_runtime(
        agent_id=agent_id,
        handle=workspace_handle,
        _headers=headers,
    )
    deadline = time.monotonic() + _RUNTIME_READY_TIMEOUT_SECONDS
    last_state: object | None = None
    while time.monotonic() < deadline:
        state = api.agent_runtime_v1_observe_agent_runtime(
            agent_id=agent_id,
            handle=workspace_handle,
            _headers=headers,
        )
        last_state = state
        if state.state.actions.use_runner and state.runtime.workspace_path:
            return
        time.sleep(1)
    raise AssertionError(
        f"Runtime Runner did not report a workspace path: {last_state!r}"
    )


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
    suffix = _unique()
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
