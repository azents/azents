"""Provider-owned Kubernetes resource identity and redaction tests."""

import dataclasses
import hashlib

import pytest

from azents_runtime_provider_kubernetes.kubernetes_api import (
    ConfigMapResource,
    ObjectMeta,
    SecretResource,
)
from azents_runtime_provider_kubernetes.owned_resources import (
    ANNOTATION_ARTIFACT_DIGEST,
    ANNOTATION_CA_FINGERPRINT,
    ANNOTATION_CONFIGURATION_DIGEST,
    ANNOTATION_CONFIGURATION_SEQUENCE,
    ANNOTATION_POLICY_DIGEST,
    LABEL_DESIRED_GENERATION,
    LABEL_RESOURCE_ROLE,
    InvalidOwnedResourceMetadata,
    InvalidRuntimeId,
    OwnedResourceAnnotations,
    OwnedResourceIdentity,
    ResourceRole,
    config_map_comparison_view,
    owned_annotations,
    owned_labels,
    proxy_policy_resource_name,
    resource_name,
    secret_comparison_view,
    validate_owned_metadata,
    validate_proxy_policy_metadata,
)


def test_resource_names_are_deterministic_for_every_owned_role() -> None:
    assert {role: resource_name("runtime-1", role) for role in ResourceRole} == {
        ResourceRole.RUNTIME_POD: "azents-runtime-runtime-1",
        ResourceRole.WORKSPACE_PVC: "azents-runtime-runtime-1-workspace",
        ResourceRole.NIX_STORE_PVC: "azents-runtime-runtime-1-nix",
        ResourceRole.RUNTIME_NETWORK_POLICY: "azents-runtime-runtime-1-execution",
        ResourceRole.RUNTIME_CA: "azents-runtime-runtime-1-ca",
        ResourceRole.PROXY_POLICY: "azents-runtime-runtime-1-proxy-policy",
        ResourceRole.PROXY_SERVICE: "azents-runtime-runtime-1-proxy",
        ResourceRole.PROXY_POD: "azents-runtime-runtime-1-proxy",
        ResourceRole.PROXY_INGRESS_NETWORK_POLICY: (
            "azents-runtime-runtime-1-proxy-ingress"
        ),
        ResourceRole.PROXY_EGRESS_NETWORK_POLICY: (
            "azents-runtime-runtime-1-proxy-egress"
        ),
    }


def test_proxy_policy_resource_name_is_digest_revisioned_and_bounded() -> None:
    digest = "a" * 64

    assert proxy_policy_resource_name("runtime-1", digest) == (
        "azents-runtime-runtime-1-proxy-policy-aaaaaaaaaaaa"
    )
    assert len(proxy_policy_resource_name("a" * 210, digest)) <= 253
    with pytest.raises(InvalidOwnedResourceMetadata, match="SHA-256"):
        proxy_policy_resource_name("runtime-1", "invalid")


def test_proxy_policy_metadata_requires_exact_digest_revision() -> None:
    identity = OwnedResourceIdentity(
        provider_id="provider-k8s",
        runtime_id="runtime-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
    )
    digest = "a" * 64
    metadata = ObjectMeta(
        name=proxy_policy_resource_name(identity.runtime_id, digest),
        namespace="azents-runtime",
        labels=owned_labels(
            identity,
            ResourceRole.PROXY_POLICY,
            desired_generation=7,
        ),
        annotations={},
    )

    validate_proxy_policy_metadata(
        metadata,
        identity,
        desired_generation=7,
        policy_digest=digest,
    )
    with pytest.raises(InvalidOwnedResourceMetadata, match="name mismatch"):
        validate_proxy_policy_metadata(
            metadata,
            identity,
            desired_generation=7,
            policy_digest="b" * 64,
        )


@pytest.mark.parametrize(
    "runtime_id",
    ("", "../foreign", "UPPERCASE", "a" * 240),
)
def test_resource_name_rejects_invalid_kubernetes_identity(runtime_id: str) -> None:
    with pytest.raises(InvalidRuntimeId):
        resource_name(runtime_id, ResourceRole.RUNTIME_CA)


def test_owned_metadata_requires_exact_name_and_labels() -> None:
    identity = OwnedResourceIdentity(
        provider_id="provider-k8s",
        runtime_id="runtime-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
    )
    labels = owned_labels(
        identity,
        ResourceRole.RUNTIME_CA,
        desired_generation=7,
    )
    metadata = ObjectMeta(
        name=resource_name(identity.runtime_id, ResourceRole.RUNTIME_CA),
        namespace="azents-runtime",
        labels=labels,
        annotations={},
    )

    validate_owned_metadata(
        metadata,
        identity,
        ResourceRole.RUNTIME_CA,
        desired_generation=7,
    )
    assert labels[LABEL_RESOURCE_ROLE] == ResourceRole.RUNTIME_CA
    assert labels[LABEL_DESIRED_GENERATION] == "7"

    with pytest.raises(InvalidOwnedResourceMetadata, match="desired-generation"):
        validate_owned_metadata(
            metadata,
            identity,
            ResourceRole.RUNTIME_CA,
            desired_generation=8,
        )
    with pytest.raises(InvalidOwnedResourceMetadata, match="name mismatch"):
        validate_owned_metadata(
            dataclasses.replace(metadata, name="azents-runtime-runtime-1-ca-copy"),
            identity,
            ResourceRole.RUNTIME_CA,
            desired_generation=7,
        )
    with pytest.raises(InvalidOwnedResourceMetadata, match="managed-by"):
        validate_owned_metadata(
            dataclasses.replace(
                metadata,
                labels={**labels, "azents/managed-by": "foreign-controller"},
            ),
            identity,
            ResourceRole.RUNTIME_CA,
            desired_generation=7,
        )

    stable_metadata = dataclasses.replace(
        metadata,
        labels=owned_labels(
            identity,
            ResourceRole.RUNTIME_CA,
            desired_generation=None,
        ),
    )
    validate_owned_metadata(
        stable_metadata,
        identity,
        ResourceRole.RUNTIME_CA,
        desired_generation=None,
    )
    with pytest.raises(InvalidOwnedResourceMetadata, match="desired-generation"):
        validate_owned_metadata(
            metadata,
            identity,
            ResourceRole.RUNTIME_CA,
            desired_generation=None,
        )


def test_owned_annotations_accept_only_safe_digest_evidence() -> None:
    digest = "a" * 64

    annotations = owned_annotations(
        OwnedResourceAnnotations(
            configuration_sequence=12,
            configuration_digest=digest,
            policy_digest=digest,
            ca_fingerprint=digest,
            artifact_digest=digest,
        )
    )

    assert annotations == {
        ANNOTATION_CONFIGURATION_SEQUENCE: "12",
        ANNOTATION_CONFIGURATION_DIGEST: digest,
        ANNOTATION_POLICY_DIGEST: digest,
        ANNOTATION_CA_FINGERPRINT: digest,
        ANNOTATION_ARTIFACT_DIGEST: digest,
    }
    with pytest.raises(InvalidOwnedResourceMetadata, match="SHA-256"):
        owned_annotations(
            OwnedResourceAnnotations(
                configuration_sequence=12,
                configuration_digest="raw-policy",
                policy_digest=None,
                ca_fingerprint=None,
                artifact_digest=None,
            )
        )


def test_secret_and_config_map_comparison_views_are_digest_only() -> None:
    metadata = ObjectMeta(
        name="runtime-artifact",
        namespace="azents-runtime",
        labels={},
        annotations={},
    )
    private_value = b"private-key-material"
    policy_value = '{"allowed_domains":["example.com"]}'

    secret_view = secret_comparison_view(
        SecretResource(
            metadata=metadata,
            data={"mitmproxy-ca.pem": private_value},
            secret_type="Opaque",
            immutable=None,
        )
    )
    config_map_view = config_map_comparison_view(
        ConfigMapResource(
            metadata=metadata,
            data={"policy.json": policy_value},
            immutable=True,
        )
    )

    assert secret_view.key_digests == {
        "mitmproxy-ca.pem": hashlib.sha256(private_value).hexdigest()
    }
    assert config_map_view.key_digests == {
        "policy.json": hashlib.sha256(policy_value.encode()).hexdigest()
    }
    assert private_value.decode() not in repr(secret_view)
    assert policy_value not in repr(config_map_view)
