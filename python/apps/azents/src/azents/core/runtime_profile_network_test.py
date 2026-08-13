"""Hierarchical Runtime network Profile contract tests."""

import pytest

from azents.core.runtime_profile import (
    JsonValue,
    KubernetesContainerResources,
    KubernetesPodProfileSpecV2,
    KubernetesPodProfileSpecV3,
    KubernetesSchedulingModule,
    KubernetesWorkspaceVolume,
    RuntimeConfigurationApplicationImpact,
    RuntimeConfigurationResolutionStatus,
    RuntimeDirectNetworkAccess,
    RuntimeInfrastructureProfileKind,
    RuntimeNetworkMode,
    RuntimeNetworkPolicyModule,
    RuntimeNoNetworkAccess,
    RuntimeProviderProfileContractSupport,
    RuntimeProxyDomainMode,
    RuntimeProxyDomainPolicyAllowlist,
    RuntimeProxyDomainPolicyUnrestricted,
    RuntimeProxyRequiredNetworkAccess,
    WorkspaceRuntimeNetworkRestrictionDirect,
    WorkspaceRuntimeNetworkRestrictionInherit,
    WorkspaceRuntimeNetworkRestrictionNoNetwork,
    WorkspaceRuntimeNetworkRestrictionProxyRequired,
    WorkspaceRuntimeProfilePolicyV1,
    WorkspaceRuntimeProfilePolicyV2,
    classify_runtime_configuration_application,
    compose_workspace_runtime_profile,
    evaluate_runtime_profile_compatibility,
    parse_runtime_infrastructure_profile_api_spec,
    parse_workspace_runtime_profile_policy,
    project_runtime_network,
    required_runtime_profile_capabilities,
)


def _legacy_direct_profile() -> KubernetesPodProfileSpecV2:
    return KubernetesPodProfileSpecV2(
        profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
        contract_family="kubernetes.pod-profile",
        schema_version=2,
        runner_resources=KubernetesContainerResources(
            cpu_request_millicores=None,
            cpu_limit_millicores=None,
            memory_request_bytes=None,
            memory_limit_bytes=None,
        ),
        workspace_volume=KubernetesWorkspaceVolume(
            storage_class_name="standard",
            storage_request_bytes=1,
        ),
        network_policy=RuntimeNetworkPolicyModule(
            allowed_cidrs=("10.0.0.0/8",),
            denied_cidrs=("10.1.0.0/16",),
        ),
        service_account_name=None,
        scheduling=KubernetesSchedulingModule(node_selector={}, tolerations=()),
        dind=None,
    )


def _direct_network() -> RuntimeDirectNetworkAccess:
    return RuntimeDirectNetworkAccess(
        mode=RuntimeNetworkMode.DIRECT,
        allowed_cidrs=("10.0.0.0/8",),
        denied_cidrs=("10.1.0.0/16",),
    )


def _proxy_network(
    domain_policy: (
        RuntimeProxyDomainPolicyUnrestricted | RuntimeProxyDomainPolicyAllowlist
    )
    | None = None,
) -> RuntimeProxyRequiredNetworkAccess:
    return RuntimeProxyRequiredNetworkAccess(
        mode=RuntimeNetworkMode.PROXY_REQUIRED,
        allowed_cidrs=("10.0.0.0/8",),
        denied_cidrs=("10.1.0.0/16",),
        domain_policy=domain_policy
        or RuntimeProxyDomainPolicyUnrestricted(
            mode=RuntimeProxyDomainMode.UNRESTRICTED,
            allowed_domains=(),
            denied_domains=(),
        ),
    )


def _profile_v3(
    network_access: (
        RuntimeDirectNetworkAccess
        | RuntimeProxyRequiredNetworkAccess
        | RuntimeNoNetworkAccess
    ),
) -> KubernetesPodProfileSpecV3:
    legacy = _legacy_direct_profile()
    return KubernetesPodProfileSpecV3(
        profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
        contract_family="kubernetes.pod-profile",
        schema_version=3,
        runner_resources=legacy.runner_resources,
        workspace_volume=legacy.workspace_volume,
        network_access=network_access,
        service_account_name=legacy.service_account_name,
        scheduling=legacy.scheduling,
        dind=legacy.dind,
    )


def _mapping(value: JsonValue, key: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise AssertionError(f"{key} must be an object")
    return value


def _resolved_configuration(
    network_access: (
        RuntimeDirectNetworkAccess
        | RuntimeProxyRequiredNetworkAccess
        | RuntimeNoNetworkAccess
    ),
    *,
    network_enforcement: dict[str, JsonValue],
    capability_revision_id: str = "capability-1",
    capability_digest: str = "a" * 64,
) -> dict[str, JsonValue]:
    return {
        "schema_version": 1,
        "provider": {
            "id": "provider-1",
            "logical_id": "provider-logical-1",
            "kind": "kubernetes",
            "capability_revision_id": capability_revision_id,
            "capability_digest": capability_digest,
        },
        "infrastructure_profile": {
            "id": "infrastructure-1",
            "version": 1,
            "digest": "b" * 64,
        },
        "workspace_runtime_profile": {
            "id": "workspace-profile-1",
            "version": 1,
            "digest": "c" * 64,
        },
        "effective_profile": _profile_v3(network_access).model_dump(mode="json"),
        "network_enforcement": network_enforcement,
    }


def test_v1_api_profile_parser_accepts_legacy_and_v3_contracts() -> None:
    """The stable API version exposes every rollout Profile contract version."""
    legacy = _legacy_direct_profile()
    strict = _profile_v3(
        _proxy_network(
            RuntimeProxyDomainPolicyAllowlist(
                mode=RuntimeProxyDomainMode.ALLOWLIST,
                allowed_domains=("*.example.com",),
                denied_domains=("blocked.example.com",),
            )
        )
    )

    assert (
        parse_runtime_infrastructure_profile_api_spec(legacy.model_dump(mode="json"))
        == legacy
    )
    assert (
        parse_runtime_infrastructure_profile_api_spec(strict.model_dump(mode="json"))
        == strict
    )
    assert project_runtime_network(strict).model_dump(mode="json") == {
        "mode": "proxy_required",
        "allowed_cidrs": ["10.0.0.0/8"],
        "denied_cidrs": ["10.1.0.0/16"],
        "domain_mode": "allowlist",
        "allowed_domains": ["*.example.com"],
        "denied_domains": ["blocked.example.com"],
    }


def test_policy_v2_parser_canonicalizes_cidrs_and_idna_domains() -> None:
    """Policy v2 canonicalizes every persisted hierarchy input."""
    parsed = parse_workspace_runtime_profile_policy(
        {
            "schema_version": 2,
            "network_restriction": {
                "mode": "proxy_required",
                "allowed_cidrs": ["10.2.0.7/16"],
                "denied_cidrs": [],
                "domain_policy": {
                    "mode": "allowlist",
                    "allowed_domains": ["BÜCHER.example.", "*.Sub.Example.com"],
                    "denied_domains": [],
                },
            },
        }
    )

    assert isinstance(parsed, WorkspaceRuntimeProfilePolicyV2)
    restriction = parsed.network_restriction
    assert isinstance(restriction, WorkspaceRuntimeNetworkRestrictionProxyRequired)
    assert restriction.allowed_cidrs == ("10.2.0.0/16",)
    assert isinstance(restriction.domain_policy, RuntimeProxyDomainPolicyAllowlist)
    assert restriction.domain_policy.allowed_domains == (
        "*.sub.example.com",
        "xn--bcher-kva.example",
    )


@pytest.mark.parametrize(
    "domain",
    [
        "https://example.com",
        "example.com:443",
        "api.*.example.com",
        "*example.com",
        "127.0.0.1",
        "[::1]",
        "example..com",
    ],
)
def test_domain_policy_rejects_non_host_pattern_shapes(domain: str) -> None:
    """Only exact hosts and leading-label wildcards are accepted."""
    with pytest.raises(ValueError):
        RuntimeProxyDomainPolicyAllowlist(
            mode=RuntimeProxyDomainMode.ALLOWLIST,
            allowed_domains=(domain,),
            denied_domains=(),
        )


def test_unrestricted_domain_policy_rejects_allowed_domains() -> None:
    """Unrestricted authority is explicit rather than list-derived."""
    with pytest.raises(
        ValueError,
        match="Unrestricted domain policy cannot declare allowed domains",
    ):
        RuntimeProxyDomainPolicyUnrestricted(
            mode=RuntimeProxyDomainMode.UNRESTRICTED,
            allowed_domains=("example.com",),
            denied_domains=(),
        )


def test_policy_v2_converts_legacy_direct_profile_to_proxy_v3() -> None:
    """Policy v2 can narrow a legacy direct Profile into proxy-required v3."""
    effective = compose_workspace_runtime_profile(
        _legacy_direct_profile(),
        WorkspaceRuntimeProfilePolicyV2(
            schema_version=2,
            network_restriction=WorkspaceRuntimeNetworkRestrictionProxyRequired(
                mode=RuntimeNetworkMode.PROXY_REQUIRED,
                allowed_cidrs=("10.2.0.0/16",),
                denied_cidrs=("10.2.1.0/24",),
                domain_policy=RuntimeProxyDomainPolicyAllowlist(
                    mode=RuntimeProxyDomainMode.ALLOWLIST,
                    allowed_domains=("api.example.com", "*.services.example.com"),
                    denied_domains=("blocked.services.example.com",),
                ),
            ),
        ),
    )

    assert effective["schema_version"] == 3
    network = _mapping(effective["network_access"], "network_access")
    assert network == {
        "mode": "proxy_required",
        "allowed_cidrs": ["10.2.0.0/16"],
        "denied_cidrs": ["10.1.0.0/16", "10.2.1.0/24"],
        "domain_policy": {
            "mode": "allowlist",
            "allowed_domains": ["*.services.example.com", "api.example.com"],
            "denied_domains": ["blocked.services.example.com"],
        },
    }


def test_policy_v2_inherit_preserves_v3_authority() -> None:
    """Explicit inherit preserves a canonical Profile v3 network authority."""
    profile = _profile_v3(_proxy_network())
    effective = compose_workspace_runtime_profile(
        profile,
        WorkspaceRuntimeProfilePolicyV2(
            schema_version=2,
            network_restriction=WorkspaceRuntimeNetworkRestrictionInherit(
                mode="inherit"
            ),
        ),
    )

    assert effective == profile.model_dump(mode="json")


@pytest.mark.parametrize(
    "profile",
    [
        _legacy_direct_profile(),
        _profile_v3(_direct_network()),
        _profile_v3(_proxy_network()),
        _profile_v3(RuntimeNoNetworkAccess(mode=RuntimeNetworkMode.NO_NETWORK)),
    ],
)
def test_policy_v2_no_network_is_valid_below_every_kubernetes_mode(
    profile: KubernetesPodProfileSpecV2 | KubernetesPodProfileSpecV3,
) -> None:
    """No-network is the most restrictive Workspace authority."""
    effective = compose_workspace_runtime_profile(
        profile,
        WorkspaceRuntimeProfilePolicyV2(
            schema_version=2,
            network_restriction=WorkspaceRuntimeNetworkRestrictionNoNetwork(
                mode=RuntimeNetworkMode.NO_NETWORK
            ),
        ),
    )

    assert effective["schema_version"] == 3
    assert effective["network_access"] == {"mode": "no_network"}


def test_policy_v2_rejects_mode_expansion() -> None:
    """A Workspace cannot restore direct authority below proxy-required."""
    with pytest.raises(ValueError, match="workspace_network_mode_expands"):
        compose_workspace_runtime_profile(
            _profile_v3(_proxy_network()),
            WorkspaceRuntimeProfilePolicyV2(
                schema_version=2,
                network_restriction=WorkspaceRuntimeNetworkRestrictionDirect(
                    mode=RuntimeNetworkMode.DIRECT,
                    allowed_cidrs=(),
                    denied_cidrs=(),
                ),
            ),
        )


def test_policy_v2_rejects_domain_expansion_beyond_parent_allowlist() -> None:
    """The parent wildcard does not authorize its own apex."""
    parent = _profile_v3(
        _proxy_network(
            RuntimeProxyDomainPolicyAllowlist(
                mode=RuntimeProxyDomainMode.ALLOWLIST,
                allowed_domains=("*.example.com",),
                denied_domains=("blocked.example.com",),
            )
        )
    )

    with pytest.raises(ValueError, match="workspace_network_domain_expands"):
        compose_workspace_runtime_profile(
            parent,
            WorkspaceRuntimeProfilePolicyV2(
                schema_version=2,
                network_restriction=WorkspaceRuntimeNetworkRestrictionProxyRequired(
                    mode=RuntimeNetworkMode.PROXY_REQUIRED,
                    allowed_cidrs=(),
                    denied_cidrs=(),
                    domain_policy=RuntimeProxyDomainPolicyAllowlist(
                        mode=RuntimeProxyDomainMode.ALLOWLIST,
                        allowed_domains=("example.com",),
                        denied_domains=(),
                    ),
                ),
            ),
        )


def test_policy_v2_allows_narrower_wildcard_and_unions_denials() -> None:
    """Narrower wildcard authority retains every inherited denial."""
    effective = compose_workspace_runtime_profile(
        _profile_v3(
            _proxy_network(
                RuntimeProxyDomainPolicyAllowlist(
                    mode=RuntimeProxyDomainMode.ALLOWLIST,
                    allowed_domains=("*.example.com",),
                    denied_domains=("blocked.example.com",),
                )
            )
        ),
        WorkspaceRuntimeProfilePolicyV2(
            schema_version=2,
            network_restriction=WorkspaceRuntimeNetworkRestrictionProxyRequired(
                mode=RuntimeNetworkMode.PROXY_REQUIRED,
                allowed_cidrs=(),
                denied_cidrs=(),
                domain_policy=RuntimeProxyDomainPolicyAllowlist(
                    mode=RuntimeProxyDomainMode.ALLOWLIST,
                    allowed_domains=("*.service.example.com",),
                    denied_domains=("private.service.example.com",),
                ),
            ),
        ),
    )

    network = _mapping(effective["network_access"], "network_access")
    assert network["domain_policy"] == {
        "mode": "allowlist",
        "allowed_domains": ["*.service.example.com"],
        "denied_domains": [
            "blocked.example.com",
            "private.service.example.com",
        ],
    }


def test_policy_v2_empty_domain_allowlist_is_explicit_deny_all() -> None:
    """An empty allowlist never becomes unrestricted domain authority."""
    effective = compose_workspace_runtime_profile(
        _legacy_direct_profile(),
        WorkspaceRuntimeProfilePolicyV2(
            schema_version=2,
            network_restriction=WorkspaceRuntimeNetworkRestrictionProxyRequired(
                mode=RuntimeNetworkMode.PROXY_REQUIRED,
                allowed_cidrs=(),
                denied_cidrs=(),
                domain_policy=RuntimeProxyDomainPolicyAllowlist(
                    mode=RuntimeProxyDomainMode.ALLOWLIST,
                    allowed_domains=(),
                    denied_domains=(),
                ),
            ),
        ),
    )

    network = _mapping(effective["network_access"], "network_access")
    assert network["domain_policy"] == {
        "mode": "allowlist",
        "allowed_domains": [],
        "denied_domains": [],
    }


def test_policy_v1_rejects_strict_v3_profile() -> None:
    """Legacy Policy v1 cannot inherit strict infrastructure authority."""
    with pytest.raises(
        ValueError,
        match="workspace_network_restriction_unsupported",
    ):
        compose_workspace_runtime_profile(
            _profile_v3(_proxy_network()),
            WorkspaceRuntimeProfilePolicyV1(
                schema_version=1,
                network_restriction=None,
            ),
        )


@pytest.mark.parametrize(
    ("network_access", "mode_capabilities"),
    [
        (_direct_network(), {"runtime.network-policy"}),
        (
            _proxy_network(),
            {"runtime.inspected-http-proxy", "runtime.network-enforcement"},
        ),
        (
            RuntimeNoNetworkAccess(mode=RuntimeNetworkMode.NO_NETWORK),
            {"runtime.external-network-denial", "runtime.network-enforcement"},
        ),
    ],
)
def test_profile_v3_requires_mode_specific_capabilities(
    network_access: (
        RuntimeDirectNetworkAccess
        | RuntimeProxyRequiredNetworkAccess
        | RuntimeNoNetworkAccess
    ),
    mode_capabilities: set[str],
) -> None:
    """Strict compatibility follows the effective network mode."""
    profile = _profile_v3(network_access)
    required = required_runtime_profile_capabilities(profile)
    compatibility = evaluate_runtime_profile_compatibility(
        profile,
        [
            RuntimeProviderProfileContractSupport(
                profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
                contract_family="kubernetes.pod-profile",
                schema_versions=frozenset({3}),
                capabilities=required - mode_capabilities,
            )
        ],
        provider_protocol_version="agent-runtime-provider-kubernetes-v3",
    )

    assert mode_capabilities.issubset(required)
    assert not compatibility.compatible
    assert compatibility.missing_capabilities == tuple(sorted(mode_capabilities))


def test_profile_v3_requires_provider_protocol_v3() -> None:
    """Profile v3 stays blocked until the Provider implements protocol v3."""
    profile = _profile_v3(_proxy_network())
    support = RuntimeProviderProfileContractSupport(
        profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
        contract_family="kubernetes.pod-profile",
        schema_versions=frozenset({3}),
        capabilities=required_runtime_profile_capabilities(profile),
    )

    blocked = evaluate_runtime_profile_compatibility(
        profile,
        [support],
        provider_protocol_version="agent-runtime-provider-kubernetes-v2",
    )
    ready = evaluate_runtime_profile_compatibility(
        profile,
        [support],
        provider_protocol_version="agent-runtime-provider-kubernetes-v3",
    )

    assert not blocked.compatible
    assert blocked.reason_code == "profile_protocol_version_unsupported"
    assert ready.compatible
    assert ready.reason_code is None


def test_capability_revision_identity_only_is_in_place() -> None:
    """An unchanged material configuration ignores capability row identity."""
    enforcement: dict[str, JsonValue] = {
        "mode": "proxy_required",
        "policy_digest": "policy-a",
        "proxy_artifact_revision": "proxy-a",
        "mandatory_service_mapping_revision": "hosts-a",
        "trust_revision": "trust-a",
    }
    applied = _resolved_configuration(
        _proxy_network(),
        network_enforcement=enforcement,
    )
    desired = _resolved_configuration(
        _proxy_network(),
        network_enforcement=enforcement,
        capability_revision_id="capability-2",
        capability_digest="b" * 64,
    )

    assert (
        classify_runtime_configuration_application(
            desired_status=RuntimeConfigurationResolutionStatus.READY,
            desired_configuration=desired,
            applied_configuration=applied,
        )
        is RuntimeConfigurationApplicationImpact.IN_PLACE
    )


def test_direct_policy_digest_change_is_in_place() -> None:
    """Direct CIDR policy changes update only the enforcement resource."""
    applied_enforcement: dict[str, JsonValue] = {
        "mode": "direct",
        "policy_digest": "policy-a",
    }
    desired_enforcement = {**applied_enforcement, "policy_digest": "policy-b"}

    assert (
        classify_runtime_configuration_application(
            desired_status=RuntimeConfigurationResolutionStatus.READY,
            desired_configuration=_resolved_configuration(
                _direct_network(),
                network_enforcement=desired_enforcement,
            ),
            applied_configuration=_resolved_configuration(
                _direct_network(),
                network_enforcement=applied_enforcement,
            ),
        )
        is RuntimeConfigurationApplicationImpact.IN_PLACE
    )


@pytest.mark.parametrize("changed_key", ["policy_digest", "proxy_artifact_revision"])
def test_proxy_only_changes_are_in_place(changed_key: str) -> None:
    """Policy and immutable proxy artifact changes replace only proxy resources."""
    applied_enforcement: dict[str, JsonValue] = {
        "mode": "proxy_required",
        "policy_digest": "policy-a",
        "proxy_artifact_revision": "proxy-a",
        "mandatory_service_mapping_revision": "hosts-a",
        "trust_revision": "trust-a",
    }
    desired_enforcement = {**applied_enforcement, changed_key: "changed"}

    assert (
        classify_runtime_configuration_application(
            desired_status=RuntimeConfigurationResolutionStatus.READY,
            desired_configuration=_resolved_configuration(
                _proxy_network(),
                network_enforcement=desired_enforcement,
            ),
            applied_configuration=_resolved_configuration(
                _proxy_network(),
                network_enforcement=applied_enforcement,
            ),
        )
        is RuntimeConfigurationApplicationImpact.IN_PLACE
    )


@pytest.mark.parametrize(
    "changed_key",
    ["mandatory_service_mapping_revision", "trust_revision"],
)
def test_runtime_trust_and_hosts_changes_require_recreation(changed_key: str) -> None:
    """Runtime trust and hosts inputs require Runtime replacement."""
    applied_enforcement: dict[str, JsonValue] = {
        "mode": "proxy_required",
        "policy_digest": "policy-a",
        "proxy_artifact_revision": "proxy-a",
        "mandatory_service_mapping_revision": "hosts-a",
        "trust_revision": "trust-a",
    }
    desired_enforcement = {**applied_enforcement, changed_key: "changed"}

    assert (
        classify_runtime_configuration_application(
            desired_status=RuntimeConfigurationResolutionStatus.READY,
            desired_configuration=_resolved_configuration(
                _proxy_network(),
                network_enforcement=desired_enforcement,
            ),
            applied_configuration=_resolved_configuration(
                _proxy_network(),
                network_enforcement=applied_enforcement,
            ),
        )
        is RuntimeConfigurationApplicationImpact.RECREATE
    )


def test_no_network_policy_digest_change_requires_recreation() -> None:
    """No-network enforcement changes replace the Runtime Pod."""
    applied_enforcement: dict[str, JsonValue] = {
        "mode": "no_network",
        "policy_digest": "policy-a",
        "mandatory_service_mapping_revision": "hosts-a",
    }
    desired_enforcement = {**applied_enforcement, "policy_digest": "policy-b"}

    assert (
        classify_runtime_configuration_application(
            desired_status=RuntimeConfigurationResolutionStatus.READY,
            desired_configuration=_resolved_configuration(
                RuntimeNoNetworkAccess(mode=RuntimeNetworkMode.NO_NETWORK),
                network_enforcement=desired_enforcement,
            ),
            applied_configuration=_resolved_configuration(
                RuntimeNoNetworkAccess(mode=RuntimeNetworkMode.NO_NETWORK),
                network_enforcement=applied_enforcement,
            ),
        )
        is RuntimeConfigurationApplicationImpact.RECREATE
    )


def test_network_mode_change_requires_recreation() -> None:
    """Changing network mode replaces the Runtime Pod."""
    assert (
        classify_runtime_configuration_application(
            desired_status=RuntimeConfigurationResolutionStatus.READY,
            desired_configuration=_resolved_configuration(
                RuntimeNoNetworkAccess(mode=RuntimeNetworkMode.NO_NETWORK),
                network_enforcement={
                    "mode": "no_network",
                    "policy_digest": "policy-b",
                    "mandatory_service_mapping_revision": "hosts-a",
                },
            ),
            applied_configuration=_resolved_configuration(
                _proxy_network(),
                network_enforcement={
                    "mode": "proxy_required",
                    "policy_digest": "policy-a",
                    "proxy_artifact_revision": "proxy-a",
                    "mandatory_service_mapping_revision": "hosts-a",
                    "trust_revision": "trust-a",
                },
            ),
        )
        is RuntimeConfigurationApplicationImpact.RECREATE
    )
