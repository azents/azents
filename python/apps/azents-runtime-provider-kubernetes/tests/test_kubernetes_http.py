"""Kubernetes HTTP resource mapping tests."""

import dataclasses
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from azents_runtime_provider_kubernetes.kubernetes_api import (
    ConfigMapResource,
    ConfigMapVolume,
    ContainerResourceClaim,
    ContainerResources,
    ContainerSecurityContext,
    ContainerSpec,
    ContainerTerminationEvidence,
    EmptyDirVolume,
    EnvVar,
    ExecAction,
    HostAlias,
    IpBlock,
    KeyToPath,
    LabelSelector,
    LocalObjectReference,
    NetworkPolicyEgressRule,
    NetworkPolicyIngressRule,
    NetworkPolicyPeer,
    NetworkPolicyPort,
    NetworkPolicyResource,
    NetworkPolicySpec,
    ObjectMeta,
    PodDnsConfig,
    PodDnsConfigOption,
    PodResource,
    PodSecurityContext,
    PodSpec,
    Probe,
    SeccompProfile,
    SecretResource,
    SecretVolume,
    ServicePort,
    ServiceResource,
    ServiceSpec,
    VolumeMount,
)
from azents_runtime_provider_kubernetes.kubernetes_http import (
    POD_WATCH_TIMEOUT,
    KubernetesApiRequestError,
    KubernetesHttpApi,
    config_map_manifest,
    config_map_resource,
    network_policy_manifest,
    network_policy_resource,
    pod_manifest,
    pod_resource,
    secret_manifest,
    secret_resource,
    service_manifest,
    service_resource,
)

type JsonObject = dict[str, Any]
type StubResponse = JsonObject | None | KubernetesApiRequestError


@dataclasses.dataclass(frozen=True)
class RecordedRequest:
    """One Kubernetes API request captured by the test adapter."""

    method: str
    path: str
    allow_not_found: bool
    params: Mapping[str, str] | None
    json: JsonObject | None
    headers: Mapping[str, str] | None


class RecordingKubernetesHttpApi(KubernetesHttpApi):
    """Kubernetes HTTP adapter with deterministic request responses."""

    def __init__(self, responses: Sequence[StubResponse]) -> None:
        self.responses = deque(responses)
        self.requests: list[RecordedRequest] = []

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        allow_not_found: bool = False,
        params: Mapping[str, str] | None = None,
        json: JsonObject | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JsonObject | None:
        self.requests.append(
            RecordedRequest(
                method=method,
                path=path,
                allow_not_found=allow_not_found,
                params=params,
                json=json,
                headers=headers,
            )
        )
        response = self.responses.popleft()
        if isinstance(response, KubernetesApiRequestError):
            raise response
        return response


def test_pod_watch_has_no_total_or_socket_read_timeout() -> None:
    assert POD_WATCH_TIMEOUT.total is None
    assert POD_WATCH_TIMEOUT.sock_connect == 30
    assert POD_WATCH_TIMEOUT.sock_read is None


def test_pod_manifest_omits_container_resources_when_unset() -> None:
    pod = _pod(resources=None)

    manifest = pod_manifest(pod)

    container = manifest["spec"]["containers"][0]
    assert "resources" not in container


def test_pod_manifest_preserves_generic_resource_requirements() -> None:
    resources = ContainerResources(
        requests={"cpu": "500m", "ephemeral-storage": "1Gi"},
        limits={"memory": "2Gi", "nvidia.com/gpu": 1},
        claims=(ContainerResourceClaim(name="gpu-claim", request="gpu"),),
    )
    pod = _pod(resources=resources)

    manifest = pod_manifest(pod)

    assert manifest["spec"]["containers"][0]["resources"] == {
        "requests": {
            "cpu": "500m",
            "ephemeral-storage": "1Gi",
        },
        "limits": {
            "memory": "2Gi",
            "nvidia.com/gpu": 1,
        },
        "claims": [
            {
                "name": "gpu-claim",
                "request": "gpu",
            }
        ],
    }


def test_pod_manifest_preserves_zero_resource_requests() -> None:
    pod = _pod(
        resources=ContainerResources(
            requests={"cpu": "0", "memory": "0"},
            limits={"cpu": "1", "memory": "2Gi"},
            claims=None,
        )
    )

    manifest = pod_manifest(pod)

    assert manifest["spec"]["containers"][0]["resources"] == {
        "requests": {"cpu": "0", "memory": "0"},
        "limits": {"cpu": "1", "memory": "2Gi"},
    }


def test_pod_manifest_preserves_image_pull_secrets() -> None:
    pod = _pod(resources=None)
    pod = PodResource(
        metadata=pod.metadata,
        spec=PodSpec(
            service_account_name=pod.spec.service_account_name,
            automount_service_account_token=pod.spec.automount_service_account_token,
            image_pull_secrets=(LocalObjectReference(name="ecr-pull-secret"),),
            security_context=pod.spec.security_context,
            node_selector=pod.spec.node_selector,
            tolerations=pod.spec.tolerations,
            dns_policy=pod.spec.dns_policy,
            dns_config=pod.spec.dns_config,
            host_aliases=pod.spec.host_aliases,
            containers=pod.spec.containers,
            volumes=pod.spec.volumes,
        ),
    )

    manifest = pod_manifest(pod)

    assert manifest["spec"]["imagePullSecrets"] == [{"name": "ecr-pull-secret"}]


def test_pod_resource_returns_none_for_absent_container_resources() -> None:
    pod = pod_resource(
        {
            "metadata": {
                "name": "runtime",
                "namespace": "azents-runtime",
            },
            "spec": {
                "containers": [
                    {
                        "name": "runner",
                        "image": "runner:latest",
                    }
                ],
            },
        }
    )

    assert pod.spec.containers[0].resources is None


def test_pod_resource_preserves_image_pull_secrets() -> None:
    pod = pod_resource(
        {
            "metadata": {
                "name": "runtime",
                "namespace": "azents-runtime",
            },
            "spec": {
                "imagePullSecrets": [{"name": "ecr-pull-secret"}],
                "containers": [
                    {
                        "name": "runner",
                        "image": "runner:latest",
                    }
                ],
            },
        }
    )

    assert pod.spec.image_pull_secrets == (
        LocalObjectReference(name="ecr-pull-secret"),
    )


def test_pod_resource_preserves_generic_resource_requirements() -> None:
    pod = pod_resource(
        {
            "metadata": {
                "name": "runtime",
                "namespace": "azents-runtime",
            },
            "spec": {
                "containers": [
                    {
                        "name": "runner",
                        "image": "runner:latest",
                        "resources": {
                            "requests": {
                                "cpu": "500m",
                                "ephemeral-storage": "1Gi",
                            },
                            "limits": {
                                "memory": "2Gi",
                                "nvidia.com/gpu": 1,
                            },
                            "claims": [
                                {
                                    "name": "gpu-claim",
                                    "request": "gpu",
                                }
                            ],
                        },
                    }
                ],
            },
        }
    )

    assert pod.spec.containers[0].resources == ContainerResources(
        requests={
            "cpu": "500m",
            "ephemeral-storage": "1Gi",
        },
        limits={
            "memory": "2Gi",
            "nvidia.com/gpu": 1,
        },
        claims=(ContainerResourceClaim(name="gpu-claim", request="gpu"),),
    )


def test_pod_policy_topology_round_trips() -> None:
    runner = _pod(resources=None).spec.containers[0]
    engine = ContainerSpec(
        name="container-engine",
        image="engine@sha256:test",
        command=("dockerd",),
        args=(),
        working_dir="/",
        resources=None,
        security_context=runner.security_context,
        readiness_probe=Probe(
            exec_action=ExecAction(
                command=("test", "-S", "/var/run/azents-engine/docker.sock")
            ),
            initial_delay_seconds=1,
            period_seconds=2,
            timeout_seconds=1,
            failure_threshold=30,
        ),
        env=(),
        volume_mounts=(
            VolumeMount(
                name="container-engine-socket",
                mount_path="/var/run/azents-engine",
                read_only=False,
            ),
        ),
    )
    pod = PodResource(
        metadata=ObjectMeta(
            name="runtime",
            namespace="azents-runtime",
            labels={"azents/execution-policy-managed": "true"},
            annotations={},
        ),
        spec=PodSpec(
            service_account_name=None,
            automount_service_account_token=False,
            image_pull_secrets=(),
            security_context=PodSecurityContext(
                run_as_user=None,
                run_as_group=None,
                fs_group=1000,
                fs_group_change_policy="OnRootMismatch",
            ),
            node_selector={},
            tolerations=(),
            dns_policy="None",
            dns_config=PodDnsConfig(
                nameservers=("127.0.0.1",),
                searches=(),
                options=(
                    PodDnsConfigOption(name="ndots", value="1"),
                    PodDnsConfigOption(name="attempts", value="1"),
                    PodDnsConfigOption(name="timeout", value="1"),
                ),
            ),
            host_aliases=(
                HostAlias(
                    ip="10.96.0.10",
                    hostnames=("runtime-control.azents.svc",),
                ),
            ),
            containers=(runner, engine),
            volumes=(
                EmptyDirVolume(
                    name="container-engine-socket",
                    medium="Memory",
                    size_limit="16Mi",
                ),
                EmptyDirVolume(
                    name="container-engine-storage",
                    medium=None,
                    size_limit=8_589_934_592,
                ),
                ConfigMapVolume(
                    name="proxy-policy",
                    config_map_name="runtime-proxy-policy",
                    items=(
                        KeyToPath(
                            key="policy.json",
                            path="policy.json",
                            mode=0o444,
                        ),
                    ),
                    default_mode=0o444,
                ),
                SecretVolume(
                    name="runtime-ca",
                    secret_name="runtime-ca",
                    items=(
                        KeyToPath(
                            key="ca.crt",
                            path="ca.crt",
                            mode=0o444,
                        ),
                    ),
                    default_mode=0o444,
                ),
            ),
        ),
    )

    manifest = pod_manifest(pod)

    assert pod_resource(manifest) == pod
    assert manifest["spec"]["automountServiceAccountToken"] is False
    assert "serviceAccountName" not in manifest["spec"]
    assert manifest["spec"]["volumes"][1] == {
        "name": "container-engine-storage",
        "emptyDir": {"sizeLimit": 8_589_934_592},
    }
    assert manifest["spec"]["dnsPolicy"] == "None"
    assert manifest["spec"]["dnsConfig"] == {
        "nameservers": ["127.0.0.1"],
        "searches": [],
        "options": [
            {"name": "ndots", "value": "1"},
            {"name": "attempts", "value": "1"},
            {"name": "timeout", "value": "1"},
        ],
    }
    assert manifest["spec"]["hostAliases"] == [
        {
            "ip": "10.96.0.10",
            "hostnames": ["runtime-control.azents.svc"],
        }
    ]
    assert manifest["spec"]["volumes"][3] == {
        "name": "runtime-ca",
        "secret": {
            "secretName": "runtime-ca",
            "items": [{"key": "ca.crt", "path": "ca.crt", "mode": 0o444}],
            "defaultMode": 0o444,
        },
    }


def test_runtime_default_seccomp_round_trip() -> None:
    pod = _pod(resources=None)
    runner = pod.spec.containers[0]
    pod = dataclasses.replace(
        pod,
        spec=dataclasses.replace(
            pod.spec,
            containers=(
                dataclasses.replace(
                    runner,
                    security_context=dataclasses.replace(
                        runner.security_context,
                        seccomp_profile=SeccompProfile(
                            profile_type="RuntimeDefault",
                            localhost_profile=None,
                        ),
                    ),
                ),
            ),
        ),
    )

    manifest = pod_manifest(pod)

    assert pod_resource(manifest) == pod
    container_security = manifest["spec"]["containers"][0]["securityContext"]
    assert container_security["seccompProfile"] == {"type": "RuntimeDefault"}


def test_pod_resource_decodes_bounded_termination_evidence() -> None:
    manifest = pod_manifest(_pod(resources=None))
    manifest["status"] = {
        "phase": "Failed",
        "containerStatuses": [
            {
                "name": "runner",
                "state": {
                    "terminated": {
                        "exitCode": 137,
                        "reason": "OOMKilled",
                        "message": "must not enter bounded evidence",
                    }
                },
            }
        ],
    }

    pod = pod_resource(manifest)

    assert pod.status is not None
    assert pod.status.termination_evidence == ContainerTerminationEvidence(
        container_name="runner",
        exit_code=137,
        reason="OOMKilled",
        oom_killed=True,
    )


def test_network_policy_round_trips_runtime_evidence_and_rules() -> None:
    network_policy = _network_policy()

    manifest = network_policy_manifest(network_policy)

    assert network_policy_resource(manifest) == network_policy
    assert manifest["spec"]["egress"] == [
        {
            "to": [
                {
                    "ipBlock": {
                        "cidr": "203.0.113.0/24",
                        "except": ["203.0.113.128/25"],
                    }
                }
            ],
            "ports": [{"protocol": "TCP", "port": 443}],
        }
    ]


@pytest.mark.asyncio
async def test_network_policy_create_posts_desired_resource() -> None:
    network_policy = _network_policy()
    api = RecordingKubernetesHttpApi((None, {}))

    await api.apply_network_policy(network_policy)

    assert [request.method for request in api.requests] == ["GET", "POST"]
    create = api.requests[1]
    assert create.json == network_policy_manifest(network_policy)
    assert create.json is not None
    assert "resourceVersion" not in create.json["metadata"]


@pytest.mark.asyncio
async def test_network_policy_replace_removes_legacy_fields() -> None:
    network_policy = _network_policy()
    existing = network_policy_manifest(network_policy)
    existing["metadata"]["resourceVersion"] = "42"
    existing["metadata"]["labels"]["legacy-label"] = "retained-by-merge-patch"
    existing["spec"]["podSelector"]["matchLabels"].update(
        {
            "azents/desired-generation": "11",
            "azents/provider-generation": "14557",
        }
    )
    existing["spec"]["egress"].append({"to": [{"ipBlock": {"cidr": "10.0.0.0/8"}}]})
    api = RecordingKubernetesHttpApi((existing, {}))

    await api.apply_network_policy(network_policy)

    assert [request.method for request in api.requests] == ["GET", "PUT"]
    replacement = api.requests[1].json
    assert replacement is not None
    assert replacement["metadata"] == {
        "name": "azents-runtime-runtime-1-execution",
        "namespace": "azents-runtime",
        "labels": {"azents/runtime-id": "runtime-1"},
        "annotations": {"azents/execution-policy-digest": "digest"},
        "resourceVersion": "42",
    }
    assert replacement["spec"] == network_policy_manifest(network_policy)["spec"]


@pytest.mark.asyncio
async def test_network_policy_replace_retries_one_conflict() -> None:
    network_policy = _network_policy()
    first = network_policy_manifest(network_policy)
    first["metadata"]["resourceVersion"] = "42"
    second = network_policy_manifest(network_policy)
    second["metadata"]["resourceVersion"] = "43"
    conflict = KubernetesApiRequestError(
        method="PUT",
        path="/networkpolicies/runtime",
        status=409,
        reason="Conflict",
        body="resource version changed",
    )
    api = RecordingKubernetesHttpApi((first, conflict, second, {}))

    await api.apply_network_policy(network_policy)

    assert [request.method for request in api.requests] == [
        "GET",
        "PUT",
        "GET",
        "PUT",
    ]
    first_replace = api.requests[1].json
    second_replace = api.requests[3].json
    assert first_replace is not None
    assert second_replace is not None
    assert first_replace["metadata"]["resourceVersion"] == "42"
    assert second_replace["metadata"]["resourceVersion"] == "43"


def test_core_resources_round_trip_without_secret_text_coercion() -> None:
    metadata = ObjectMeta(
        name="runtime-proxy",
        namespace="azents-runtime",
        labels={"azents/runtime-id": "runtime-1"},
        annotations={"azents/policy-digest": "digest"},
    )
    service = ServiceResource(
        metadata=metadata,
        spec=ServiceSpec(
            service_type="ClusterIP",
            cluster_ip="10.96.0.20",
            selector={"azents/resource-role": "proxy"},
            ports=(
                ServicePort(
                    name="proxy",
                    protocol="TCP",
                    port=8080,
                    target_port="proxy",
                ),
            ),
        ),
    )
    config_map = ConfigMapResource(
        metadata=metadata,
        data={"policy.json": '{"schema_version":1}'},
        immutable=True,
    )
    secret = SecretResource(
        metadata=metadata,
        data={"ca.crt": b"\x00public\n", "mitmproxy-ca.pem": b"private\n"},
        secret_type="Opaque",
        immutable=False,
    )

    assert service_resource(service_manifest(service)) == service
    assert config_map_resource(config_map_manifest(config_map)) == config_map
    assert secret_resource(secret_manifest(secret)) == secret
    assert secret_manifest(secret)["data"] == {
        "ca.crt": "AHB1YmxpYwo=",
        "mitmproxy-ca.pem": "cHJpdmF0ZQo=",
    }


def test_secret_resource_rejects_invalid_base64() -> None:
    manifest = secret_manifest(
        SecretResource(
            metadata=ObjectMeta(
                name="runtime-ca",
                namespace="azents-runtime",
                labels={},
                annotations={},
            ),
            data={"ca.crt": b"public"},
            secret_type="Opaque",
            immutable=None,
        )
    )
    manifest["data"]["ca.crt"] = "***"

    with pytest.raises(RuntimeError, match="invalid base64"):
        secret_resource(manifest)


@pytest.mark.asyncio
async def test_core_resource_methods_use_exact_namespaced_paths() -> None:
    metadata = ObjectMeta(
        name="runtime-proxy",
        namespace="azents-runtime",
        labels={"azents/runtime-id": "runtime-1"},
        annotations={},
    )
    service = ServiceResource(
        metadata=metadata,
        spec=ServiceSpec(
            service_type="ClusterIP",
            cluster_ip=None,
            selector={"azents/resource-role": "proxy"},
            ports=(
                ServicePort(
                    name="proxy",
                    protocol="TCP",
                    port=8080,
                    target_port=8080,
                ),
            ),
        ),
    )
    config_map = ConfigMapResource(
        metadata=metadata,
        data={"policy.json": "{}"},
        immutable=None,
    )
    secret = SecretResource(
        metadata=metadata,
        data={"ca.crt": b"public"},
        secret_type="Opaque",
        immutable=None,
    )
    api = RecordingKubernetesHttpApi((None, {}, None, {}, None, {}))

    await api.apply_service(service)
    await api.apply_config_map(config_map)
    await api.apply_secret(secret)

    assert [(item.method, item.path) for item in api.requests] == [
        ("GET", "/api/v1/namespaces/azents-runtime/services/runtime-proxy"),
        ("POST", "/api/v1/namespaces/azents-runtime/services"),
        ("GET", "/api/v1/namespaces/azents-runtime/configmaps/runtime-proxy"),
        ("POST", "/api/v1/namespaces/azents-runtime/configmaps"),
        ("GET", "/api/v1/namespaces/azents-runtime/secrets/runtime-proxy"),
        ("POST", "/api/v1/namespaces/azents-runtime/secrets"),
    ]


def _network_policy() -> NetworkPolicyResource:
    return NetworkPolicyResource(
        metadata=ObjectMeta(
            name="azents-runtime-runtime-1-execution",
            namespace="azents-runtime",
            labels={"azents/runtime-id": "runtime-1"},
            annotations={"azents/execution-policy-digest": "digest"},
        ),
        spec=NetworkPolicySpec(
            pod_selector=LabelSelector(
                match_labels={
                    "azents/runtime-id": "runtime-1",
                    "azents/execution-policy-managed": "true",
                }
            ),
            policy_types=("Ingress", "Egress"),
            ingress=(
                NetworkPolicyIngressRule(
                    peers=(
                        NetworkPolicyPeer(
                            namespace_selector=LabelSelector(
                                match_labels={
                                    "kubernetes.io/metadata.name": "azents-runtime"
                                }
                            ),
                            pod_selector=LabelSelector(
                                match_labels={"azents/runtime-id": "runtime-1"}
                            ),
                            ip_block=None,
                        ),
                    ),
                    ports=(NetworkPolicyPort(protocol="TCP", port=8080),),
                ),
            ),
            egress=(
                NetworkPolicyEgressRule(
                    peers=(
                        NetworkPolicyPeer(
                            namespace_selector=None,
                            pod_selector=None,
                            ip_block=IpBlock(
                                cidr="203.0.113.0/24",
                                except_cidrs=("203.0.113.128/25",),
                            ),
                        ),
                    ),
                    ports=(NetworkPolicyPort(protocol="TCP", port=443),),
                ),
            ),
        ),
    )


@pytest.mark.asyncio
async def test_network_policy_list_uses_exact_label_selector() -> None:
    network_policy = _network_policy()
    api = RecordingKubernetesHttpApi(
        ({"items": [network_policy_manifest(network_policy)]},)
    )

    result = await api.list_network_policies(
        {
            "azents/managed-by": "azents-runtime-provider-kubernetes",
            "azents/runtime-id": "runtime-1",
        },
        "azents-runtime",
    )

    assert result == (network_policy,)
    assert len(api.requests) == 1
    request = api.requests[0]
    assert request.method == "GET"
    assert request.path == (
        "/apis/networking.k8s.io/v1/namespaces/azents-runtime/networkpolicies"
    )
    assert request.params == {
        "labelSelector": (
            "azents/managed-by=azents-runtime-provider-kubernetes,"
            "azents/runtime-id=runtime-1"
        )
    }


def _pod(resources: ContainerResources | None) -> PodResource:
    return PodResource(
        metadata=ObjectMeta(
            name="runtime",
            namespace="azents-runtime",
            labels={},
            annotations={},
        ),
        spec=PodSpec(
            service_account_name=None,
            automount_service_account_token=False,
            image_pull_secrets=(),
            security_context=None,
            node_selector={},
            tolerations=(),
            dns_policy=None,
            dns_config=None,
            host_aliases=(),
            containers=(
                ContainerSpec(
                    name="runner",
                    image="runner:latest",
                    command=None,
                    args=(),
                    working_dir="/workspace/agent",
                    resources=resources,
                    security_context=ContainerSecurityContext(
                        privileged=False,
                        allow_privilege_escalation=False,
                        read_only_root_filesystem=False,
                        run_as_non_root=True,
                        run_as_user=1000,
                        run_as_group=1000,
                        capabilities_add=(),
                        capabilities_drop=("ALL",),
                        proc_mount=None,
                        seccomp_profile=None,
                    ),
                    readiness_probe=None,
                    env=(EnvVar(name="AZ_RUNTIME_ID", value="runtime"),),
                    volume_mounts=(),
                ),
            ),
            volumes=(),
        ),
    )
