"""Deterministic strict-network control-plane E2E journeys."""

from __future__ import annotations

from typing import Literal

import azentsadminclient
import azentspublicclient
import pytest
from azentspublicclient.api.agent_runtime_v1_api import AgentRuntimeV1Api
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.runtime_profile_v1_api import RuntimeProfileV1Api
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_runtime_response import AgentRuntimeResponse
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.runtime_configuration_status import (
    RuntimeConfigurationStatus,
)
from azentspublicclient.models.runtime_proxy_domain_policy import (
    RuntimeProxyDomainPolicy,
)
from azentspublicclient.models.runtime_proxy_domain_policy_allowlist import (
    RuntimeProxyDomainPolicyAllowlist,
)
from azentspublicclient.models.secrets import Secrets
from azentspublicclient.models.workspace_runtime_network_restriction import (
    WorkspaceRuntimeNetworkRestriction,
)
from azentspublicclient.models.workspace_runtime_network_restriction_no_network import (
    WorkspaceRuntimeNetworkRestrictionNoNetwork,
)
from azentspublicclient.models.workspace_runtime_network_restriction_proxy_required import (  # noqa: E501
    WorkspaceRuntimeNetworkRestrictionProxyRequired,
)
from azentspublicclient.models.workspace_runtime_profile_create_request import (
    WorkspaceRuntimeProfileCreateRequest,
)
from azentspublicclient.models.workspace_runtime_profile_policy import (
    WorkspaceRuntimeProfilePolicy,
)
from azentspublicclient.models.workspace_runtime_profile_policy_v2 import (
    WorkspaceRuntimeProfilePolicyV2,
)

from support.strict_network_control_plane import (
    StrictNetworkControlPlaneFixture,
    load_control_plane_evidence,
)
from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    unique,
    wait_until,
)

StrictMode = Literal["proxy_required", "no_network"]


@pytest.mark.parametrize("mode", ["proxy_required", "no_network"])
def test_strict_network_modes_reach_applied_control_plane_state(
    mode: StrictMode,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    strict_network_control_plane: StrictNetworkControlPlaneFixture,
) -> None:
    """Validate API, Provider, and Runner evidence without packet claims."""
    suffix = unique()
    token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"strict-network-{mode}-{suffix}@example.com",
    )
    handle = f"strict-network-{mode.replace('_', '-')}-{suffix}"
    headers = {"Authorization": f"Bearer {token}"}
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Strict Network {mode} {suffix}",
            workspace_handle=handle,
            owner_name=f"Owner {suffix}",
        ),
        _headers=headers,
    )
    integration = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-success",
            secrets=Secrets(ApiKeySecrets(api_key="sk-strict-network-control-plane")),
        ),
        _headers=headers,
    )
    model_selection = model_selection_from_first_candidate(
        azents_public_server_url,
        token,
        handle,
        integration.id,
    )

    profile_api = RuntimeProfileV1Api(public_api_client)
    selectable = profile_api.runtime_profile_v1_list_selectable_infrastructure_profiles(
        handle=handle,
        _headers=headers,
    )
    candidates = [
        profile
        for profile in selectable.items
        if profile.provider_id == strict_network_control_plane.provider_id
    ]
    assert len(candidates) == 1
    profile = profile_api.runtime_profile_v1_create_workspace_runtime_profile(
        handle=handle,
        workspace_runtime_profile_create_request=WorkspaceRuntimeProfileCreateRequest(
            infrastructure_profile_id=candidates[0].id,
            display_name=f"Strict {mode} {suffix}",
            description="Deterministic control-plane-only strict-network journey.",
            policy=_workspace_policy(mode),
        ),
        _headers=headers,
    )
    assert profile.effective_network is not None
    assert profile.effective_network.mode.value == mode

    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=handle,
        agent_create_request=AgentCreateRequest(
            name=f"Strict Network {mode} {suffix}",
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
            type=AgentType.PUBLIC,
            runtime_profile_id=profile.id,
        ),
        _headers=headers,
    )
    runtime_api = AgentRuntimeV1Api(public_api_client)
    started = runtime_api.agent_runtime_v1_start_agent_runtime(
        agent_id=agent.id,
        handle=handle,
        _headers=headers,
    )
    assert started.configuration is not None
    assert started.configuration.desired is not None
    assert started.configuration.desired.network is not None
    assert started.configuration.desired.network.mode.value == mode

    applied_runtime: AgentRuntimeResponse | None = None

    def applied_with_evidence() -> bool:
        nonlocal applied_runtime
        applied_runtime = runtime_api.agent_runtime_v1_get_agent_runtime(
            agent_id=agent.id,
            handle=handle,
            _headers=headers,
        )
        configuration = applied_runtime.configuration
        if (
            configuration is None
            or configuration.status is not RuntimeConfigurationStatus.APPLIED
            or configuration.desired is None
            or configuration.applied is None
            or applied_runtime.runtime is None
        ):
            return False
        desired = configuration.desired
        applied = configuration.applied
        if desired.network is None or applied.network is None:
            return False
        matching_evidence = [
            item
            for item in load_control_plane_evidence(
                strict_network_control_plane.evidence_path
            )
            if item.event == "command_completed"
            and item.runtime_id == applied_runtime.runtime.id
            and item.network_mode == mode
            and item.configuration_sequence == desired.sequence
            and item.desired_generation == desired.target_generation
            and item.digest == desired.digest
        ]
        return bool(matching_evidence)

    wait_until(
        applied_with_evidence,
        timeout=120,
        interval=1,
        message=f"strict-network {mode} did not reach applied control-plane state",
    )
    assert applied_runtime is not None
    assert applied_runtime.runtime is not None
    assert applied_runtime.configuration is not None
    desired = applied_runtime.configuration.desired
    applied = applied_runtime.configuration.applied
    assert desired is not None
    assert applied is not None
    assert desired.network is not None
    assert applied.network is not None
    assert desired.network.mode.value == mode
    assert applied.network.mode.value == mode
    assert applied.sequence == desired.sequence
    assert applied.digest == desired.digest
    assert desired.provider_reported_digest == desired.digest
    assert desired.runner_reported_digest == desired.digest
    assert desired.provider_acknowledged_at is not None
    assert desired.runner_observed_at is not None
    assert applied.applied_at is not None
    matching = [
        item
        for item in load_control_plane_evidence(
            strict_network_control_plane.evidence_path
        )
        if item.event == "command_completed"
        and item.runtime_id == applied_runtime.runtime.id
        and item.configuration_sequence == desired.sequence
    ]
    assert matching
    assert all(item.classification == "control_plane_only" for item in matching)
    assert all(item.provider_acknowledgement for item in matching)
    assert all(item.runner_process_started for item in matching)


def _workspace_policy(mode: StrictMode) -> WorkspaceRuntimeProfilePolicy:
    """Build one generated-client Policy v2 wrapper for a strict mode."""
    if mode == "proxy_required":
        restriction = WorkspaceRuntimeNetworkRestriction(
            WorkspaceRuntimeNetworkRestrictionProxyRequired(
                mode="proxy_required",
                allowed_cidrs=["203.0.113.0/24"],
                denied_cidrs=["203.0.113.128/25"],
                domain_policy=RuntimeProxyDomainPolicy(
                    RuntimeProxyDomainPolicyAllowlist(
                        mode="allowlist",
                        allowed_domains=["example.com"],
                        denied_domains=["blocked.example.com"],
                    )
                ),
            )
        )
    else:
        restriction = WorkspaceRuntimeNetworkRestriction(
            WorkspaceRuntimeNetworkRestrictionNoNetwork(mode="no_network")
        )
    return WorkspaceRuntimeProfilePolicy(
        WorkspaceRuntimeProfilePolicyV2(
            schema_version=2,
            network_restriction=restriction,
        )
    )
