"""Workspace Runtime Profile Public API projection tests."""

import datetime

from azents.api.public.runtime_profile.v1.data import (
    SelectableInfrastructureProfileResponse,
    WorkspaceRuntimeProfileResponse,
)
from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.core.runtime_profile import (
    RuntimeInfrastructureProfileKind,
    RuntimeNetworkMode,
    RuntimeProfileCompatibility,
    RuntimeProfileLifecycle,
)
from azents.repos.runtime_profile.data import (
    RuntimeInfrastructureProfile,
    WorkspaceRuntimeProfile,
)
from azents.repos.runtime_provider.data import RuntimeProvider
from azents.services.runtime_profile_workspace.service import (
    SelectableInfrastructureProfileProjection,
    WorkspaceRuntimeProfileProjection,
)


def _infrastructure_spec() -> dict[str, object]:
    """Build one direct Kubernetes v3 infrastructure Profile document."""
    return {
        "profile_kind": "kubernetes_pod",
        "contract_family": "kubernetes.pod-profile",
        "schema_version": 3,
        "runner_resources": {
            "cpu_request_millicores": None,
            "cpu_limit_millicores": None,
            "memory_request_bytes": None,
            "memory_limit_bytes": None,
        },
        "workspace_volume": {
            "storage_class_name": "standard",
            "storage_request_bytes": 1,
        },
        "network_access": {
            "mode": "direct",
            "allowed_cidrs": ["10.0.0.0/8"],
            "denied_cidrs": ["10.1.0.0/16"],
        },
        "service_account_name": None,
        "scheduling": {
            "node_selector": {},
            "tolerations": [],
        },
        "dind": None,
    }


def _infrastructure(now: datetime.datetime) -> RuntimeInfrastructureProfile:
    """Build one Provider-owned infrastructure Profile."""
    return RuntimeInfrastructureProfile(
        id="infrastructure-1",
        provider_id="provider-row-1",
        profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
        display_name="Strict Kubernetes",
        description="Kubernetes runtime",
        lifecycle=RuntimeProfileLifecycle.ACTIVE,
        contract_family="kubernetes.pod-profile",
        schema_version=3,
        spec=_infrastructure_spec(),
        required_capabilities=("runtime.network-policy",),
        version=2,
        digest="a" * 64,
        created_by_user_id="admin-1",
        updated_by_user_id="admin-1",
        created_at=now,
        updated_at=now,
    )


def _provider(now: datetime.datetime) -> RuntimeProvider:
    """Build one active Kubernetes Provider projection source."""
    return RuntimeProvider(
        id="provider-row-1",
        provider_id="system-kubernetes",
        scope=RuntimeProviderScope.SYSTEM,
        workspace_id=None,
        kind=RuntimeProviderKind.KUBERNETES,
        display_name="Kubernetes",
        registration_method=RuntimeProviderRegistrationMethod.ADMIN,
        enabled=True,
        lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
        availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
        current_contract_revision_id="capability-1",
        active_config_revision_id=None,
        admin_version=1,
        capabilities={},
        config_schema=None,
        metadata=None,
        created_at=now,
        updated_at=now,
    )


def test_selectable_profile_exposes_v3_spec_and_infrastructure_network() -> None:
    """Selectable choices include the typed v3 contract and its maximum authority."""
    now = datetime.datetime(2026, 8, 12, tzinfo=datetime.UTC)
    response = SelectableInfrastructureProfileResponse.convert_from(
        SelectableInfrastructureProfileProjection(
            profile=_infrastructure(now),
            provider=_provider(now),
            compatibility=RuntimeProfileCompatibility(
                compatible=True,
                reason_code=None,
                missing_capabilities=(),
                incompatible_constraints=(),
            ),
            capability_revision_id="capability-1",
        )
    )

    assert response.spec.schema_version == 3
    assert response.infrastructure_network.model_dump(mode="json") == {
        "mode": "direct",
        "allowed_cidrs": ["10.0.0.0/8"],
        "denied_cidrs": ["10.1.0.0/16"],
        "domain_mode": None,
        "allowed_domains": [],
        "denied_domains": [],
    }


def test_workspace_policy_v2_exposes_infrastructure_and_effective_network() -> None:
    """Project inherited and effective authority without client composition."""
    now = datetime.datetime(2026, 8, 12, tzinfo=datetime.UTC)
    profile = WorkspaceRuntimeProfile(
        id="profile-1",
        workspace_id="workspace-1",
        provider_id="provider-row-1",
        infrastructure_profile_id="infrastructure-1",
        display_name="Proxy only",
        description="Inspected web access",
        lifecycle=RuntimeProfileLifecycle.ACTIVE,
        policy={
            "schema_version": 2,
            "network_restriction": {
                "mode": "proxy_required",
                "allowed_cidrs": ["10.2.0.7/16"],
                "denied_cidrs": ["10.2.1.0/24"],
                "domain_policy": {
                    "mode": "allowlist",
                    "allowed_domains": ["*.Example.com"],
                    "denied_domains": ["Blocked.Example.com"],
                },
            },
        },
        version=3,
        digest="b" * 64,
        created_by_workspace_user_id="workspace-user-1",
        updated_by_workspace_user_id="workspace-user-1",
        created_at=now,
        updated_at=now,
    )
    response = WorkspaceRuntimeProfileResponse.convert_from(
        WorkspaceRuntimeProfileProjection(
            profile=profile,
            infrastructure_profile=_infrastructure(now),
            provider=_provider(now),
            available=True,
            reason_code=None,
            compatibility=RuntimeProfileCompatibility(
                compatible=True,
                reason_code=None,
                missing_capabilities=(),
                incompatible_constraints=(),
            ),
            capability_revision_id="capability-1",
        )
    )

    assert response.policy.schema_version == 2
    assert response.infrastructure_network is not None
    assert response.infrastructure_network.mode is RuntimeNetworkMode.DIRECT
    assert response.effective_network is not None
    assert response.effective_network.model_dump(mode="json") == {
        "mode": "proxy_required",
        "allowed_cidrs": ["10.2.0.0/16"],
        "denied_cidrs": ["10.1.0.0/16", "10.2.1.0/24"],
        "domain_mode": "allowlist",
        "allowed_domains": ["*.example.com"],
        "denied_domains": ["blocked.example.com"],
    }
