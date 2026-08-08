"""Runtime configuration document and evidence contract tests."""

import dataclasses

import pytest

from azents_runtime_control.runtime_configuration import (
    DockerContainerProfileV1,
    DockerContainerProfileV2,
    JsonValue,
    KubernetesPodProfileV1,
    KubernetesPodProfileV2,
    RuntimeConfigurationEnvelope,
    RuntimeConfigurationEvidence,
    RuntimeProcessContainmentModuleV1,
    canonical_runtime_configuration_json,
    parse_runtime_configuration_envelope,
    runtime_configuration_from_json,
)


def test_docker_container_profile_parses_as_typed_configuration() -> None:
    parsed = parse_runtime_configuration_envelope(
        _envelope(_document("docker")),
        desired_generation=3,
        expected_provider_kind="docker",
    )

    assert isinstance(parsed.effective_profile, DockerContainerProfileV1)
    assert parsed.provider.id == "provider-resource-1"
    assert parsed.effective_profile.network_name == "azents-runtime"
    assert parsed.effective_profile.runner_resources.cpu_limit_millicores == 1000


def test_kubernetes_pod_profile_parses_all_supported_controls() -> None:
    parsed = parse_runtime_configuration_envelope(
        _envelope(_document("kubernetes")),
        desired_generation=3,
        expected_provider_kind="kubernetes",
    )

    profile = parsed.effective_profile
    assert isinstance(profile, KubernetesPodProfileV1)
    assert profile.workspace_volume.storage_class_name == "gp3"
    assert profile.network_policy.allowed_cidrs == ("10.0.0.0/8",)
    assert profile.scheduling.node_selector == {"runtime": "isolated"}
    assert profile.scheduling.tolerations[0].toleration_seconds == 30
    assert profile.dind is not None
    assert profile.dind.docker_storage_bytes == 8_589_934_592


def test_docker_container_profile_v2_parses_containment() -> None:
    document = _document("docker")
    document["effective_profile"] = _docker_profile_v2(contained=True)

    parsed = parse_runtime_configuration_envelope(
        _envelope(document),
        desired_generation=3,
        expected_provider_kind="docker",
    )

    profile = parsed.effective_profile
    assert isinstance(profile, DockerContainerProfileV2)
    assert isinstance(
        profile.process_containment,
        RuntimeProcessContainmentModuleV1,
    )


def test_kubernetes_pod_profile_v2_parses_without_containment() -> None:
    document = _document("kubernetes")
    document["effective_profile"] = _kubernetes_profile_v2(contained=False)

    parsed = parse_runtime_configuration_envelope(
        _envelope(document),
        desired_generation=3,
        expected_provider_kind="kubernetes",
    )

    profile = parsed.effective_profile
    assert isinstance(profile, KubernetesPodProfileV2)
    assert profile.process_containment is None


def test_kubernetes_v2_rejects_containment_with_nested_docker() -> None:
    document = _document("kubernetes")
    document["effective_profile"] = _kubernetes_profile_v2(contained=True)
    effective_profile = document["effective_profile"]
    assert isinstance(effective_profile, dict)
    effective_profile["dind"] = _kubernetes_profile()["dind"]

    with pytest.raises(
        ValueError,
        match="Process containment cannot be combined with nested Docker",
    ):
        parse_runtime_configuration_envelope(
            _envelope(document),
            desired_generation=3,
            expected_provider_kind="kubernetes",
        )


def test_profile_v2_requires_explicit_containment_field() -> None:
    document = _document("docker")
    profile = _docker_profile_v2(contained=False)
    del profile["process_containment"]
    document["effective_profile"] = profile

    with pytest.raises(ValueError, match="document shape"):
        parse_runtime_configuration_envelope(
            _envelope(document),
            desired_generation=3,
            expected_provider_kind="docker",
        )


def test_noncanonical_configuration_json_is_rejected() -> None:
    document = _document("docker")
    envelope = dataclasses.replace(
        _envelope(document),
        resolved_configuration_json=str(document).replace("'", '"'),
    )

    with pytest.raises(ValueError, match="not canonical"):
        parse_runtime_configuration_envelope(
            envelope,
            desired_generation=3,
            expected_provider_kind="docker",
        )


def test_command_generation_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="generation"):
        parse_runtime_configuration_envelope(
            _envelope(_document("docker")),
            desired_generation=4,
            expected_provider_kind="docker",
        )


@pytest.mark.parametrize(
    "evidence",
    (
        RuntimeConfigurationEvidence(
            revision_id="",
            digest="d" * 64,
            desired_generation=3,
        ),
        RuntimeConfigurationEvidence(
            revision_id=" revision-1 ",
            digest="d" * 64,
            desired_generation=3,
        ),
        RuntimeConfigurationEvidence(
            revision_id="revision-1",
            digest="invalid",
            desired_generation=3,
        ),
        RuntimeConfigurationEvidence(
            revision_id="revision-1",
            digest="d" * 64,
            desired_generation=-1,
        ),
    ),
)
def test_invalid_evidence_is_rejected(
    evidence: RuntimeConfigurationEvidence,
) -> None:
    with pytest.raises(ValueError, match="Runtime configuration"):
        parse_runtime_configuration_envelope(
            dataclasses.replace(_envelope(_document("docker")), evidence=evidence),
            desired_generation=evidence.desired_generation,
            expected_provider_kind="docker",
        )


def test_unknown_top_level_field_is_rejected() -> None:
    document = _document("docker")
    document["legacy_policy"] = {}

    with pytest.raises(ValueError, match="document shape"):
        parse_runtime_configuration_envelope(
            _envelope(document),
            desired_generation=3,
            expected_provider_kind="docker",
        )


def test_provider_kind_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="Provider kind"):
        parse_runtime_configuration_envelope(
            _envelope(_document("kubernetes")),
            desired_generation=3,
            expected_provider_kind="docker",
        )


def test_docker_resource_reservation_cannot_exceed_limit() -> None:
    document = _document("docker")
    effective_profile = document["effective_profile"]
    assert isinstance(effective_profile, dict)
    resources = effective_profile["runner_resources"]
    assert isinstance(resources, dict)
    resources["cpu_reservation_millicores"] = 2000

    with pytest.raises(ValueError, match="reservation cannot exceed"):
        parse_runtime_configuration_envelope(
            _envelope(document),
            desired_generation=3,
            expected_provider_kind="docker",
        )


def test_network_cidr_must_be_canonical() -> None:
    document = _document("kubernetes")
    effective_profile = document["effective_profile"]
    assert isinstance(effective_profile, dict)
    network_policy = effective_profile["network_policy"]
    assert isinstance(network_policy, dict)
    network_policy["allowed_cidrs"] = ["10.0.0.1/8"]

    with pytest.raises(ValueError, match="not canonical"):
        parse_runtime_configuration_envelope(
            _envelope(document),
            desired_generation=3,
            expected_provider_kind="kubernetes",
        )


def test_exists_toleration_cannot_include_value() -> None:
    document = _document("kubernetes")
    effective_profile = document["effective_profile"]
    assert isinstance(effective_profile, dict)
    scheduling = effective_profile["scheduling"]
    assert isinstance(scheduling, dict)
    tolerations = scheduling["tolerations"]
    assert isinstance(tolerations, list)
    toleration = tolerations[0]
    assert isinstance(toleration, dict)
    toleration["operator"] = "Exists"

    with pytest.raises(ValueError, match="must not include a value"):
        parse_runtime_configuration_envelope(
            _envelope(document),
            desired_generation=3,
            expected_provider_kind="kubernetes",
        )


def test_runtime_configuration_json_requires_an_object() -> None:
    with pytest.raises(ValueError, match="must contain an object"):
        runtime_configuration_from_json("[]")


def _envelope(
    document: dict[str, JsonValue],
) -> RuntimeConfigurationEnvelope:
    return RuntimeConfigurationEnvelope(
        evidence=RuntimeConfigurationEvidence(
            revision_id="revision-1",
            digest="d" * 64,
            desired_generation=3,
        ),
        resolved_configuration_json=canonical_runtime_configuration_json(document),
    )


def _document(provider_kind: str) -> dict[str, JsonValue]:
    effective_profile = (
        _docker_profile() if provider_kind == "docker" else _kubernetes_profile()
    )
    return {
        "schema_version": 1,
        "provider": {
            "id": "provider-resource-1",
            "logical_id": f"provider-{provider_kind}",
            "kind": provider_kind,
            "capability_revision_id": "capability-1",
            "capability_digest": "a" * 64,
        },
        "infrastructure_profile": {
            "id": "infrastructure-1",
            "version": 2,
            "digest": "b" * 64,
        },
        "workspace_runtime_profile": {
            "id": "workspace-profile-1",
            "version": 4,
            "digest": "c" * 64,
        },
        "effective_profile": effective_profile,
    }


def _docker_profile() -> dict[str, JsonValue]:
    return {
        "profile_kind": "docker_container",
        "contract_family": "docker.container-profile",
        "schema_version": 1,
        "runner_resources": {
            "cpu_reservation_millicores": 500,
            "cpu_limit_millicores": 1000,
            "memory_reservation_bytes": 536_870_912,
            "memory_limit_bytes": 1_073_741_824,
        },
        "network_name": "azents-runtime",
    }


def _docker_profile_v2(*, contained: bool) -> dict[str, JsonValue]:
    return {
        **_docker_profile(),
        "schema_version": 2,
        "process_containment": {"schema_version": 1} if contained else None,
    }


def _kubernetes_profile() -> dict[str, JsonValue]:
    return {
        "profile_kind": "kubernetes_pod",
        "contract_family": "kubernetes.pod-profile",
        "schema_version": 1,
        "runner_resources": {
            "cpu_request_millicores": 500,
            "cpu_limit_millicores": 1000,
            "memory_request_bytes": 536_870_912,
            "memory_limit_bytes": 1_073_741_824,
        },
        "workspace_volume": {
            "storage_class_name": "gp3",
            "storage_request_bytes": 10_737_418_240,
        },
        "network_policy": {
            "allowed_cidrs": ["10.0.0.0/8"],
            "denied_cidrs": ["10.10.0.0/16"],
        },
        "service_account_name": "runtime",
        "scheduling": {
            "node_selector": {"runtime": "isolated"},
            "tolerations": [
                {
                    "key": "runtime",
                    "operator": "Equal",
                    "value": "isolated",
                    "effect": "NoExecute",
                    "toleration_seconds": 30,
                }
            ],
        },
        "dind": {
            "engine_resources": {
                "cpu_request_millicores": 250,
                "cpu_limit_millicores": 500,
                "memory_request_bytes": 268_435_456,
                "memory_limit_bytes": 536_870_912,
            },
            "docker_storage_bytes": 8_589_934_592,
            "shared_temporary_storage_bytes": 10_737_418_240,
        },
    }


def _kubernetes_profile_v2(*, contained: bool) -> dict[str, JsonValue]:
    profile = {
        **_kubernetes_profile(),
        "schema_version": 2,
        "process_containment": {"schema_version": 1} if contained else None,
    }
    profile["dind"] = None
    return profile
