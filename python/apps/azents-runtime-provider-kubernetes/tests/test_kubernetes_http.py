"""Kubernetes HTTP resource mapping tests."""

from azents_runtime_provider_kubernetes.kubernetes_api import (
    ContainerResourceClaim,
    ContainerResources,
    ContainerSpec,
    EnvVar,
    LocalObjectReference,
    ObjectMeta,
    PodResource,
    PodSpec,
)
from azents_runtime_provider_kubernetes.kubernetes_http import (
    pod_manifest,
    pod_resource,
)


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
            containers=(
                ContainerSpec(
                    name="runner",
                    image="runner:latest",
                    working_dir="/workspace/agent",
                    resources=resources,
                    env=(EnvVar(name="AZ_RUNTIME_ID", value="runtime"),),
                    volume_mounts=(),
                ),
            ),
            volumes=(),
        ),
    )
