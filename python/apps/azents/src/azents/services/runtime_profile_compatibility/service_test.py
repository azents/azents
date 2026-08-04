"""Typed Runtime Profile compatibility tests."""

import pytest

from azents.core.enums import RuntimeProviderKind
from azents.testing.types import is_string_object_dict

from .service import (
    RuntimeProfileCompatibilityService,
    RuntimeProfileCompatibilityUnavailable,
)


def _contract_payload(
    *,
    capabilities: list[str] | None = None,
    constraints: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build one Kubernetes capability advertisement with Pod Profile support."""
    return {
        "schema_version": 1,
        "implementation_key": "kubernetes",
        "implementation_version": "0.1.0",
        "protocol_version": "agent-runtime-provider-kubernetes-v2",
        "core_lifecycle_operations": [
            "start",
            "stop",
            "restart",
            "reset",
            "observe",
            "terminal_delete",
        ],
        "optional_capabilities": [],
        "persistence": {
            "kind": "persistent",
            "reset_destroys_workspace": True,
            "terminal_delete_destroys_workspace": True,
        },
        "configuration_fields": [],
        "profile_contracts": [
            {
                "profile_kind": "kubernetes_pod",
                "contract_family": "kubernetes.pod-profile",
                "schema_versions": [1],
                "capabilities": capabilities
                or [
                    "kubernetes.pod-profile",
                    "runtime.resources",
                    "workspace.persistent-volume",
                    "runtime.network-policy",
                    "kubernetes.scheduling",
                ],
                "constraints": constraints or {},
            }
        ],
    }


def _profile_payload() -> dict[str, object]:
    """Build one typed Kubernetes Pod Profile document."""
    return {
        "profile_kind": "kubernetes_pod",
        "contract_family": "kubernetes.pod-profile",
        "schema_version": 1,
        "runner_resources": {
            "cpu_request_millicores": 500,
            "cpu_limit_millicores": 1000,
            "memory_request_bytes": 536870912,
            "memory_limit_bytes": 1073741824,
        },
        "workspace_volume": {
            "storage_class_name": "standard",
            "storage_request_bytes": 10737418240,
        },
        "network_policy": {
            "allowed_cidrs": ["10.0.0.1/24"],
            "denied_cidrs": [],
        },
        "service_account_name": None,
        "scheduling": {
            "node_selector": {"pool": "runtime"},
            "tolerations": [],
        },
        "dind": None,
    }


def test_prepare_profile_derives_capabilities_and_canonical_digest() -> None:
    """Client input cannot supply capability or digest authority."""
    service = RuntimeProfileCompatibilityService()

    first = service.prepare_infrastructure_profile(
        provider_kind=RuntimeProviderKind.KUBERNETES,
        provider_contract_payload=_contract_payload(),
        profile_spec_payload=_profile_payload(),
    )
    equivalent = _profile_payload()
    network = equivalent["network_policy"]
    assert is_string_object_dict(network)
    network["allowed_cidrs"] = ["10.0.0.0/24"]
    second = service.prepare_infrastructure_profile(
        provider_kind=RuntimeProviderKind.KUBERNETES,
        provider_contract_payload=_contract_payload(),
        profile_spec_payload=equivalent,
    )

    assert first.compatibility.compatible
    assert first.canonical_spec["network_policy"] == {
        "allowed_cidrs": ["10.0.0.0/24"],
        "denied_cidrs": [],
    }
    assert first.required_capabilities == (
        "kubernetes.pod-profile",
        "kubernetes.scheduling",
        "runtime.network-policy",
        "runtime.resources",
        "workspace.persistent-volume",
    )
    assert first.digest == second.digest


def test_prepare_profile_reports_exact_missing_capability() -> None:
    """Compatibility fails closed on server-derived module requirements."""
    service = RuntimeProfileCompatibilityService()
    capabilities = [
        "kubernetes.pod-profile",
        "runtime.resources",
        "workspace.persistent-volume",
        "runtime.network-policy",
    ]

    with pytest.raises(RuntimeProfileCompatibilityUnavailable) as raised:
        service.prepare_infrastructure_profile(
            provider_kind=RuntimeProviderKind.KUBERNETES,
            provider_contract_payload=_contract_payload(capabilities=capabilities),
            profile_spec_payload=_profile_payload(),
        )

    assert raised.value.code == "profile_capability_missing"
    assert raised.value.missing_capabilities == ("kubernetes.scheduling",)
    assert raised.value.incompatible_constraints == ()


def test_prepare_profile_rejects_provider_constraint_violation() -> None:
    """Compatibility rejects typed values above Provider-advertised bounds."""
    service = RuntimeProfileCompatibilityService()

    with pytest.raises(RuntimeProfileCompatibilityUnavailable) as raised:
        service.prepare_infrastructure_profile(
            provider_kind=RuntimeProviderKind.KUBERNETES,
            provider_contract_payload=_contract_payload(
                constraints={
                    "maximums": {
                        "runner_resources.cpu_limit_millicores": 750,
                        "workspace_volume.storage_request_bytes": 5_368_709_120,
                    },
                    "allowed_values": {
                        "workspace_volume.storage_class_name": ["premium"]
                    },
                }
            ),
            profile_spec_payload=_profile_payload(),
        )

    assert raised.value.code == "profile_constraint_unsupported"
    assert raised.value.missing_capabilities == ()
    assert raised.value.incompatible_constraints == (
        "runner_resources.cpu_limit_millicores",
        "workspace_volume.storage_class_name",
        "workspace_volume.storage_request_bytes",
    )


def test_prepare_profile_rejects_provider_kind_mismatch() -> None:
    """A Provider cannot accept another Provider kind's Profile contract."""
    service = RuntimeProfileCompatibilityService()

    with pytest.raises(RuntimeProfileCompatibilityUnavailable) as raised:
        service.prepare_infrastructure_profile(
            provider_kind=RuntimeProviderKind.DOCKER,
            provider_contract_payload=_contract_payload(),
            profile_spec_payload=_profile_payload(),
        )

    assert raised.value.code == "provider_contract_identity_mismatch"
