"""In-cluster Kubernetes HTTP adapter for Runtime Provider resources."""

import base64
import binascii
import dataclasses
import json
import logging
import os
import ssl
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self, cast

import aiohttp

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
    KubernetesApi,
    KubernetesResourceQuantity,
    LabelSelector,
    LabelSelectorRequirement,
    LeaseConflictError,
    LeaseResource,
    LeaseSpec,
    LocalObjectReference,
    NamespaceResource,
    NetworkPolicyEgressRule,
    NetworkPolicyIngressRule,
    NetworkPolicyPeer,
    NetworkPolicyPort,
    NetworkPolicyResource,
    NetworkPolicySpec,
    ObjectMeta,
    PersistentVolumeClaimResource,
    PersistentVolumeClaimSpec,
    PersistentVolumeClaimVolume,
    PodDnsConfig,
    PodDnsConfigOption,
    PodResource,
    PodSecurityContext,
    PodSpec,
    PodStatus,
    PodWatchEvent,
    Probe,
    SeccompProfile,
    SecretResource,
    SecretVolume,
    ServicePort,
    ServiceResource,
    ServiceSpec,
    Toleration,
    VolumeMount,
)

_SERVICE_ACCOUNT_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
_TOKEN_PATH = _SERVICE_ACCOUNT_DIR / "token"
_CA_CERT_PATH = _SERVICE_ACCOUNT_DIR / "ca.crt"
POD_WATCH_TIMEOUT = aiohttp.ClientTimeout(
    total=None,
    sock_connect=30,
    sock_read=None,
)
_LOGGER = logging.getLogger(__name__)

JsonObject = dict[str, Any]


class KubernetesApiRequestError(RuntimeError):
    """Kubernetes API returned a non-successful response."""

    def __init__(
        self,
        *,
        method: str,
        path: str,
        status: int,
        reason: str | None,
        body: str,
    ) -> None:
        """Initialize an API error with response diagnostics."""
        self.method = method
        self.path = path
        self.status = status
        self.reason = reason
        self.body = body
        super().__init__(
            f"Kubernetes API {method} {path} failed with {status} {reason}: {body}"
        )


@dataclasses.dataclass(frozen=True)
class KubernetesHttpConfig:
    """HTTP connection settings for the in-cluster Kubernetes API."""

    api_server: str
    bearer_token: str
    ca_cert_path: str | None


class KubernetesHttpApi(KubernetesApi):
    """KubernetesApi implementation using in-cluster REST calls."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialize the adapter."""
        self._session = session

    @classmethod
    async def from_in_cluster(cls) -> Self:
        """Create an adapter from service account credentials."""
        config = _load_in_cluster_config()
        ssl_context: ssl.SSLContext | bool = (
            ssl.create_default_context(cafile=config.ca_cert_path)
            if config.ca_cert_path is not None
            else False
        )
        session = aiohttp.ClientSession(
            base_url=config.api_server,
            headers={"Authorization": f"Bearer {config.bearer_token}"},
            connector=aiohttp.TCPConnector(ssl=ssl_context),
        )
        return cls(session)

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        await self._session.close()

    async def discover_api_resources(self, api_version: str) -> frozenset[str]:
        """Return resource names advertised by one Kubernetes API version."""
        path = (
            f"/api/{api_version}" if "/" not in api_version else f"/apis/{api_version}"
        )
        data = await self._request_json("GET", path)
        if data is None:
            return frozenset()
        resources = cast(list[JsonObject], data.get("resources") or [])
        return frozenset(
            str(item["name"])
            for item in resources
            if isinstance(item.get("name"), str) and "/" not in str(item["name"])
        )

    async def list_api_groups(self) -> frozenset[str]:
        """Return Kubernetes API group names visible to the Provider."""
        data = await self._request_json("GET", "/apis")
        if data is None:
            return frozenset()
        groups = cast(list[JsonObject], data.get("groups") or [])
        return frozenset(
            str(item["name"]) for item in groups if isinstance(item.get("name"), str)
        )

    async def check_resource_access(
        self,
        *,
        namespace: str | None,
        api_group: str,
        resource: str,
        verb: str,
        resource_name: str | None,
    ) -> bool:
        """Evaluate one exact Provider permission with SelfSubjectAccessReview."""
        attributes: JsonObject = {
            "group": api_group,
            "resource": resource,
            "verb": verb,
        }
        if namespace is not None:
            attributes["namespace"] = namespace
        if resource_name is not None:
            attributes["name"] = resource_name
        data = await self._request_json(
            "POST",
            "/apis/authorization.k8s.io/v1/selfsubjectaccessreviews",
            json={
                "apiVersion": "authorization.k8s.io/v1",
                "kind": "SelfSubjectAccessReview",
                "spec": {"resourceAttributes": attributes},
            },
        )
        if data is None:
            return False
        status = cast(JsonObject, data.get("status") or {})
        return status.get("allowed") is True

    async def get_namespace(self, name: str) -> NamespaceResource | None:
        """Return one Namespace by exact name."""
        data = await self._request_json(
            "GET",
            f"/api/v1/namespaces/{name}",
            allow_not_found=True,
        )
        if data is None:
            return None
        metadata = cast(JsonObject, data["metadata"])
        return NamespaceResource(
            name=str(metadata["name"]),
            labels={
                str(key): str(value)
                for key, value in cast(
                    JsonObject,
                    metadata.get("labels") or {},
                ).items()
            },
        )

    async def get_pod(self, name: str, namespace: str) -> PodResource | None:
        data = await self._request_json(
            "GET",
            f"/api/v1/namespaces/{namespace}/pods/{name}",
            allow_not_found=True,
        )
        return None if data is None else pod_resource(data)

    async def apply_pod(self, pod: PodResource) -> None:
        await self._create_or_merge_patch(
            f"/api/v1/namespaces/{pod.metadata.namespace}/pods/{pod.metadata.name}",
            f"/api/v1/namespaces/{pod.metadata.namespace}/pods",
            pod_manifest(pod),
        )

    async def delete_pod(
        self,
        name: str,
        namespace: str,
        *,
        grace_period_seconds: int | None = None,
    ) -> None:
        body = None
        if grace_period_seconds is not None:
            body = {
                "apiVersion": "v1",
                "kind": "DeleteOptions",
                "gracePeriodSeconds": grace_period_seconds,
            }
        await self._request_json(
            "DELETE",
            f"/api/v1/namespaces/{namespace}/pods/{name}",
            allow_not_found=True,
            json=body,
        )

    async def list_pods(
        self, labels: Mapping[str, str], namespace: str
    ) -> Sequence[PodResource]:
        data = await self._request_json(
            "GET",
            f"/api/v1/namespaces/{namespace}/pods",
            params={"labelSelector": _label_selector(labels)},
        )
        return tuple(pod_resource(item) for item in cast(JsonObject, data)["items"])

    async def watch_pods(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> AsyncIterator[PodWatchEvent]:
        async with self._session.request(
            "GET",
            f"/api/v1/namespaces/{namespace}/pods",
            params={
                "labelSelector": _label_selector(labels),
                "watch": "true",
                "allowWatchBookmarks": "true",
            },
            timeout=POD_WATCH_TIMEOUT,
        ) as response:
            if response.status >= 400:
                body = await response.text()
                _LOGGER.warning(
                    "Kubernetes API watch failed",
                    extra={
                        "method": "GET",
                        "path": f"/api/v1/namespaces/{namespace}/pods",
                        "status": response.status,
                        "reason": response.reason,
                        "body": body,
                    },
                )
                raise KubernetesApiRequestError(
                    method="GET",
                    path=f"/api/v1/namespaces/{namespace}/pods",
                    status=response.status,
                    reason=response.reason,
                    body=body,
                )
            async for raw_line in response.content:
                line = raw_line.strip()
                if not line:
                    continue
                event = cast(JsonObject, json.loads(line))
                event_type = str(event.get("type") or "")
                if event_type == "BOOKMARK":
                    continue
                pod = cast(JsonObject | None, event.get("object"))
                if pod is None:
                    continue
                yield PodWatchEvent(event_type=event_type, pod=pod_resource(pod))

    async def get_pvc(
        self,
        name: str,
        namespace: str,
    ) -> PersistentVolumeClaimResource | None:
        data = await self._request_json(
            "GET",
            f"/api/v1/namespaces/{namespace}/persistentvolumeclaims/{name}",
            allow_not_found=True,
        )
        return None if data is None else _pvc_resource(data)

    async def apply_pvc(self, pvc: PersistentVolumeClaimResource) -> None:
        await self._create_or_merge_patch(
            (
                f"/api/v1/namespaces/{pvc.metadata.namespace}"
                f"/persistentvolumeclaims/{pvc.metadata.name}"
            ),
            f"/api/v1/namespaces/{pvc.metadata.namespace}/persistentvolumeclaims",
            _pvc_manifest(pvc),
        )

    async def delete_pvc(self, name: str, namespace: str) -> None:
        await self._request_json(
            "DELETE",
            f"/api/v1/namespaces/{namespace}/persistentvolumeclaims/{name}",
            allow_not_found=True,
        )

    async def list_pvcs(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[PersistentVolumeClaimResource]:
        data = await self._request_json(
            "GET",
            f"/api/v1/namespaces/{namespace}/persistentvolumeclaims",
            params={"labelSelector": _label_selector(labels)},
        )
        return tuple(_pvc_resource(item) for item in cast(JsonObject, data)["items"])

    async def get_service(
        self,
        name: str,
        namespace: str,
    ) -> ServiceResource | None:
        data = await self._request_json(
            "GET",
            f"/api/v1/namespaces/{namespace}/services/{name}",
            allow_not_found=True,
        )
        return None if data is None else service_resource(data)

    async def apply_service(self, service: ServiceResource) -> None:
        namespace = service.metadata.namespace
        name = service.metadata.name
        await self._create_or_replace(
            f"/api/v1/namespaces/{namespace}/services/{name}",
            f"/api/v1/namespaces/{namespace}/services",
            service_manifest(service),
        )

    async def delete_service(self, name: str, namespace: str) -> None:
        await self._request_json(
            "DELETE",
            f"/api/v1/namespaces/{namespace}/services/{name}",
            allow_not_found=True,
        )

    async def list_services(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[ServiceResource]:
        data = await self._request_json(
            "GET",
            f"/api/v1/namespaces/{namespace}/services",
            params={"labelSelector": _label_selector(labels)},
        )
        return tuple(service_resource(item) for item in cast(JsonObject, data)["items"])

    async def get_config_map(
        self,
        name: str,
        namespace: str,
    ) -> ConfigMapResource | None:
        data = await self._request_json(
            "GET",
            f"/api/v1/namespaces/{namespace}/configmaps/{name}",
            allow_not_found=True,
        )
        return None if data is None else config_map_resource(data)

    async def apply_config_map(self, config_map: ConfigMapResource) -> None:
        namespace = config_map.metadata.namespace
        name = config_map.metadata.name
        await self._create_or_replace(
            f"/api/v1/namespaces/{namespace}/configmaps/{name}",
            f"/api/v1/namespaces/{namespace}/configmaps",
            config_map_manifest(config_map),
        )

    async def delete_config_map(self, name: str, namespace: str) -> None:
        await self._request_json(
            "DELETE",
            f"/api/v1/namespaces/{namespace}/configmaps/{name}",
            allow_not_found=True,
        )

    async def list_config_maps(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[ConfigMapResource]:
        data = await self._request_json(
            "GET",
            f"/api/v1/namespaces/{namespace}/configmaps",
            params={"labelSelector": _label_selector(labels)},
        )
        return tuple(
            config_map_resource(item) for item in cast(JsonObject, data)["items"]
        )

    async def get_secret(
        self,
        name: str,
        namespace: str,
    ) -> SecretResource | None:
        data = await self._request_json(
            "GET",
            f"/api/v1/namespaces/{namespace}/secrets/{name}",
            allow_not_found=True,
        )
        return None if data is None else secret_resource(data)

    async def apply_secret(self, secret: SecretResource) -> None:
        namespace = secret.metadata.namespace
        name = secret.metadata.name
        await self._create_or_replace(
            f"/api/v1/namespaces/{namespace}/secrets/{name}",
            f"/api/v1/namespaces/{namespace}/secrets",
            secret_manifest(secret),
        )

    async def delete_secret(self, name: str, namespace: str) -> None:
        await self._request_json(
            "DELETE",
            f"/api/v1/namespaces/{namespace}/secrets/{name}",
            allow_not_found=True,
        )

    async def list_secrets(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[SecretResource]:
        data = await self._request_json(
            "GET",
            f"/api/v1/namespaces/{namespace}/secrets",
            params={"labelSelector": _label_selector(labels)},
        )
        return tuple(secret_resource(item) for item in cast(JsonObject, data)["items"])

    async def get_network_policy(
        self,
        name: str,
        namespace: str,
    ) -> NetworkPolicyResource | None:
        data = await self._request_json(
            "GET",
            (
                f"/apis/networking.k8s.io/v1/namespaces/{namespace}"
                f"/networkpolicies/{name}"
            ),
            allow_not_found=True,
        )
        return None if data is None else network_policy_resource(data)

    async def apply_network_policy(
        self,
        network_policy: NetworkPolicyResource,
    ) -> None:
        namespace = network_policy.metadata.namespace
        name = network_policy.metadata.name
        await self._create_or_replace(
            (
                f"/apis/networking.k8s.io/v1/namespaces/{namespace}"
                f"/networkpolicies/{name}"
            ),
            f"/apis/networking.k8s.io/v1/namespaces/{namespace}/networkpolicies",
            network_policy_manifest(network_policy),
        )

    async def delete_network_policy(self, name: str, namespace: str) -> None:
        await self._request_json(
            "DELETE",
            (
                f"/apis/networking.k8s.io/v1/namespaces/{namespace}"
                f"/networkpolicies/{name}"
            ),
            allow_not_found=True,
        )

    async def list_network_policies(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[NetworkPolicyResource]:
        data = await self._request_json(
            "GET",
            f"/apis/networking.k8s.io/v1/namespaces/{namespace}/networkpolicies",
            params={"labelSelector": _label_selector(labels)},
        )
        return tuple(
            network_policy_resource(item) for item in cast(JsonObject, data)["items"]
        )

    async def get_lease(self, name: str, namespace: str) -> LeaseResource | None:
        data = await self._request_json(
            "GET",
            f"/apis/coordination.k8s.io/v1/namespaces/{namespace}/leases/{name}",
            allow_not_found=True,
        )
        return None if data is None else _lease_resource(data)

    async def apply_lease(self, lease: LeaseResource) -> None:
        resource_path = (
            f"/apis/coordination.k8s.io/v1/namespaces/"
            f"{lease.metadata.namespace}/leases/{lease.metadata.name}"
        )
        collection_path = (
            f"/apis/coordination.k8s.io/v1/namespaces/{lease.metadata.namespace}/leases"
        )
        try:
            if lease.resource_version is None:
                await self._request_json(
                    "POST",
                    collection_path,
                    json=_lease_manifest(lease),
                )
                return
            await self._request_json(
                "PUT",
                resource_path,
                json=_lease_manifest(lease),
            )
        except KubernetesApiRequestError as error:
            if error.status == 409:
                raise LeaseConflictError() from error
            raise

    async def _create_or_merge_patch(
        self,
        resource_path: str,
        collection_path: str,
        manifest: JsonObject,
    ) -> None:
        existing = await self._request_json(
            "GET",
            resource_path,
            allow_not_found=True,
        )
        if existing is None:
            await self._request_json("POST", collection_path, json=manifest)
            return
        await self._request_json(
            "PATCH",
            resource_path,
            json=manifest,
            headers={"Content-Type": "application/merge-patch+json"},
        )

    async def _create_or_replace(
        self,
        resource_path: str,
        collection_path: str,
        manifest: JsonObject,
    ) -> None:
        for attempt in range(2):
            existing = await self._request_json(
                "GET",
                resource_path,
                allow_not_found=True,
            )
            try:
                if existing is None:
                    await self._request_json("POST", collection_path, json=manifest)
                else:
                    await self._request_json(
                        "PUT",
                        resource_path,
                        json=_replacement_manifest(manifest, existing),
                    )
                return
            except KubernetesApiRequestError as error:
                if error.status != 409 or attempt == 1:
                    raise
        raise AssertionError("Kubernetes resource replacement retry exhausted")

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
        async with self._session.request(
            method,
            path,
            params=params,
            json=json,
            headers=headers,
        ) as response:
            if response.status == 404 and allow_not_found:
                return None
            if response.status >= 400:
                body = await response.text()
                _LOGGER.warning(
                    "Kubernetes API request failed",
                    extra={
                        "method": method,
                        "path": path,
                        "status": response.status,
                        "reason": response.reason,
                        "body": body,
                    },
                )
                raise KubernetesApiRequestError(
                    method=method,
                    path=path,
                    status=response.status,
                    reason=response.reason,
                    body=body,
                )
            if response.status == 204:
                return None
            return cast(JsonObject, await response.json())


def _load_in_cluster_config() -> KubernetesHttpConfig:
    host = _required_env("KUBERNETES_SERVICE_HOST")
    port = _required_env("KUBERNETES_SERVICE_PORT")
    token = _TOKEN_PATH.read_text(encoding="utf-8").strip()
    ca_cert_path = str(_CA_CERT_PATH) if _CA_CERT_PATH.exists() else None
    return KubernetesHttpConfig(
        api_server=f"https://{host}:{port}",
        bearer_token=token,
        ca_cert_path=ca_cert_path,
    )


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value:
        raise RuntimeError(f"required environment variable is missing: {name}")
    return value


def _metadata(metadata: ObjectMeta) -> JsonObject:
    return {
        "name": metadata.name,
        "namespace": metadata.namespace,
        "labels": dict(metadata.labels),
        "annotations": dict(metadata.annotations),
    }


def _replacement_manifest(manifest: JsonObject, existing: JsonObject) -> JsonObject:
    existing_metadata = existing.get("metadata")
    if not isinstance(existing_metadata, dict):
        raise RuntimeError("existing Kubernetes resource metadata is missing")
    resource_version = existing_metadata.get("resourceVersion")
    if not isinstance(resource_version, str) or not resource_version:
        raise RuntimeError("existing Kubernetes resourceVersion is missing")

    desired_metadata = manifest.get("metadata")
    if not isinstance(desired_metadata, dict):
        raise RuntimeError("desired Kubernetes resource metadata is missing")
    return {
        **manifest,
        "metadata": {
            **desired_metadata,
            "resourceVersion": resource_version,
        },
    }


def pod_manifest(pod: PodResource) -> JsonObject:
    spec: JsonObject = {
        "automountServiceAccountToken": pod.spec.automount_service_account_token,
        "containers": [
            _container_manifest(container) for container in pod.spec.containers
        ],
        "volumes": [_volume_manifest(volume) for volume in pod.spec.volumes],
    }
    if pod.spec.service_account_name is not None:
        spec["serviceAccountName"] = pod.spec.service_account_name
    if pod.spec.image_pull_secrets:
        spec["imagePullSecrets"] = [
            {"name": secret.name} for secret in pod.spec.image_pull_secrets
        ]
    if pod.spec.security_context is not None:
        security_context: JsonObject = {
            "fsGroup": pod.spec.security_context.fs_group,
            "fsGroupChangePolicy": pod.spec.security_context.fs_group_change_policy,
        }
        if pod.spec.security_context.run_as_user is not None:
            security_context["runAsUser"] = pod.spec.security_context.run_as_user
        if pod.spec.security_context.run_as_group is not None:
            security_context["runAsGroup"] = pod.spec.security_context.run_as_group
        spec["securityContext"] = security_context
    if pod.spec.node_selector:
        spec["nodeSelector"] = dict(pod.spec.node_selector)
    if pod.spec.tolerations:
        spec["tolerations"] = [
            {
                key: value
                for key, value in {
                    "key": toleration.key,
                    "operator": toleration.operator,
                    "value": toleration.value,
                    "effect": toleration.effect,
                    "tolerationSeconds": toleration.toleration_seconds,
                }.items()
                if value is not None
            }
            for toleration in pod.spec.tolerations
        ]
    if pod.spec.dns_policy is not None:
        spec["dnsPolicy"] = pod.spec.dns_policy
    if pod.spec.dns_config is not None:
        spec["dnsConfig"] = _pod_dns_config_manifest(pod.spec.dns_config)
    if pod.spec.host_aliases:
        spec["hostAliases"] = [
            {"ip": item.ip, "hostnames": list(item.hostnames)}
            for item in pod.spec.host_aliases
        ]
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": _metadata(pod.metadata),
        "spec": spec,
    }


def _container_manifest(container: ContainerSpec) -> JsonObject:
    manifest: JsonObject = {
        "name": container.name,
        "image": container.image,
        "args": list(container.args),
        "workingDir": container.working_dir,
        "securityContext": _container_security_context_manifest(
            container.security_context
        ),
        "env": [{"name": item.name, "value": item.value} for item in container.env],
        "volumeMounts": [
            {
                "name": item.name,
                "mountPath": item.mount_path,
                "readOnly": item.read_only,
            }
            for item in container.volume_mounts
        ],
    }
    if container.command is not None:
        manifest["command"] = list(container.command)
    if container.readiness_probe is not None:
        manifest["readinessProbe"] = _probe_manifest(container.readiness_probe)
    if container.resources is not None:
        manifest["resources"] = _container_resources_manifest(container.resources)
    return manifest


def _container_security_context_manifest(
    security_context: ContainerSecurityContext,
) -> JsonObject:
    manifest: JsonObject = {
        "privileged": security_context.privileged,
        "allowPrivilegeEscalation": security_context.allow_privilege_escalation,
        "readOnlyRootFilesystem": security_context.read_only_root_filesystem,
        "runAsNonRoot": security_context.run_as_non_root,
        "runAsUser": security_context.run_as_user,
        "runAsGroup": security_context.run_as_group,
        "capabilities": {
            "add": list(security_context.capabilities_add),
            "drop": list(security_context.capabilities_drop),
        },
    }
    if security_context.proc_mount is not None:
        manifest["procMount"] = security_context.proc_mount
    if security_context.seccomp_profile is not None:
        manifest["seccompProfile"] = _security_profile_manifest(
            security_context.seccomp_profile
        )
    return manifest


def _security_profile_manifest(
    profile: SeccompProfile,
) -> JsonObject:
    manifest: JsonObject = {"type": profile.profile_type}
    if profile.localhost_profile is not None:
        manifest["localhostProfile"] = profile.localhost_profile
    return manifest


def _probe_manifest(probe: Probe) -> JsonObject:
    return {
        "exec": {"command": list(probe.exec_action.command)},
        "initialDelaySeconds": probe.initial_delay_seconds,
        "periodSeconds": probe.period_seconds,
        "timeoutSeconds": probe.timeout_seconds,
        "failureThreshold": probe.failure_threshold,
    }


def _volume_manifest(
    volume: (
        PersistentVolumeClaimVolume | EmptyDirVolume | ConfigMapVolume | SecretVolume
    ),
) -> JsonObject:
    if isinstance(volume, PersistentVolumeClaimVolume):
        return {
            "name": volume.name,
            "persistentVolumeClaim": {"claimName": volume.claim_name},
        }
    if isinstance(volume, EmptyDirVolume):
        empty_dir: JsonObject = {}
        if volume.medium is not None:
            empty_dir["medium"] = volume.medium
        if volume.size_limit is not None:
            empty_dir["sizeLimit"] = volume.size_limit
        return {"name": volume.name, "emptyDir": empty_dir}
    if isinstance(volume, ConfigMapVolume):
        source: JsonObject = {
            "name": volume.config_map_name,
            "items": [_key_to_path_manifest(item) for item in volume.items],
        }
        if volume.default_mode is not None:
            source["defaultMode"] = volume.default_mode
        return {"name": volume.name, "configMap": source}
    source = {
        "secretName": volume.secret_name,
        "items": [_key_to_path_manifest(item) for item in volume.items],
    }
    if volume.default_mode is not None:
        source["defaultMode"] = volume.default_mode
    return {"name": volume.name, "secret": source}


def _key_to_path_manifest(item: KeyToPath) -> JsonObject:
    manifest: JsonObject = {"key": item.key, "path": item.path}
    if item.mode is not None:
        manifest["mode"] = item.mode
    return manifest


def _pod_dns_config_manifest(config: PodDnsConfig) -> JsonObject:
    return {
        "nameservers": list(config.nameservers),
        "searches": list(config.searches),
        "options": [
            {
                key: value
                for key, value in {"name": option.name, "value": option.value}.items()
                if value is not None
            }
            for option in config.options
        ],
    }


def _pvc_manifest(pvc: PersistentVolumeClaimResource) -> JsonObject:
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": _metadata(pvc.metadata),
        "spec": {
            "storageClassName": pvc.spec.storage_class_name,
            "accessModes": list(pvc.spec.access_modes),
            "resources": {
                "requests": {"storage": pvc.spec.storage_request},
            },
        },
    }


def service_manifest(service: ServiceResource) -> JsonObject:
    """Serialize one Provider-owned Service."""
    spec: JsonObject = {
        "type": service.spec.service_type,
        "selector": dict(service.spec.selector),
        "ports": [
            {
                key: value
                for key, value in {
                    "name": port.name,
                    "protocol": port.protocol,
                    "port": port.port,
                    "targetPort": port.target_port,
                }.items()
                if value is not None
            }
            for port in service.spec.ports
        ],
    }
    if service.spec.cluster_ip is not None:
        spec["clusterIP"] = service.spec.cluster_ip
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": _metadata(service.metadata),
        "spec": spec,
    }


def config_map_manifest(config_map: ConfigMapResource) -> JsonObject:
    """Serialize one Provider-owned ConfigMap."""
    manifest: JsonObject = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": _metadata(config_map.metadata),
        "data": dict(config_map.data),
    }
    if config_map.immutable is not None:
        manifest["immutable"] = config_map.immutable
    return manifest


def secret_manifest(secret: SecretResource) -> JsonObject:
    """Serialize one Provider-owned Secret without converting values to text."""
    manifest: JsonObject = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": _metadata(secret.metadata),
        "type": secret.secret_type,
        "data": {
            key: base64.b64encode(value).decode("ascii")
            for key, value in secret.data.items()
        },
    }
    if secret.immutable is not None:
        manifest["immutable"] = secret.immutable
    return manifest


def network_policy_manifest(network_policy: NetworkPolicyResource) -> JsonObject:
    """Serialize one Provider-owned Runtime NetworkPolicy."""
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": _metadata(network_policy.metadata),
        "spec": {
            "podSelector": _label_selector_manifest(network_policy.spec.pod_selector),
            "policyTypes": list(network_policy.spec.policy_types),
            "ingress": [
                _network_policy_ingress_manifest(rule)
                for rule in network_policy.spec.ingress
            ],
            "egress": [
                _network_policy_egress_manifest(rule)
                for rule in network_policy.spec.egress
            ],
        },
    }


def _network_policy_egress_manifest(
    rule: NetworkPolicyEgressRule,
) -> JsonObject:
    value: JsonObject = {
        "to": [_network_policy_peer_manifest(peer) for peer in rule.peers],
    }
    if rule.ports:
        value["ports"] = [
            {"protocol": port.protocol, "port": port.port} for port in rule.ports
        ]
    return value


def _network_policy_ingress_manifest(
    rule: NetworkPolicyIngressRule,
) -> JsonObject:
    value: JsonObject = {
        "from": [_network_policy_peer_manifest(peer) for peer in rule.peers],
    }
    if rule.ports:
        value["ports"] = [
            {"protocol": port.protocol, "port": port.port} for port in rule.ports
        ]
    return value


def _network_policy_peer_manifest(peer: NetworkPolicyPeer) -> JsonObject:
    value: JsonObject = {}
    if peer.namespace_selector is not None:
        value["namespaceSelector"] = _label_selector_manifest(peer.namespace_selector)
    if peer.pod_selector is not None:
        value["podSelector"] = _label_selector_manifest(peer.pod_selector)
    if peer.ip_block is not None:
        value["ipBlock"] = {
            "cidr": peer.ip_block.cidr,
            "except": list(peer.ip_block.except_cidrs),
        }
    return value


def _label_selector_manifest(selector: LabelSelector) -> JsonObject:
    manifest: JsonObject = {"matchLabels": dict(selector.match_labels)}
    if selector.match_expressions:
        manifest["matchExpressions"] = [
            {
                "key": requirement.key,
                "operator": requirement.operator,
                "values": list(requirement.values),
            }
            for requirement in selector.match_expressions
        ]
    return manifest


def _container_resources_manifest(resources: ContainerResources) -> JsonObject:
    manifest: JsonObject = {}
    if resources.requests is not None:
        manifest["requests"] = dict(resources.requests)
    if resources.limits is not None:
        manifest["limits"] = dict(resources.limits)
    if resources.claims is not None:
        manifest["claims"] = [
            {
                key: value
                for key, value in {
                    "name": claim.name,
                    "request": claim.request,
                }.items()
                if value is not None
            }
            for claim in resources.claims
        ]
    return manifest


def _resource_quantity_map(
    data: Mapping[object, object],
    key: str,
) -> Mapping[str, KubernetesResourceQuantity] | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RuntimeError(f"container.resources.{key} must be an object")
    result: dict[str, KubernetesResourceQuantity] = {}
    for resource_name, quantity in value.items():
        if not isinstance(resource_name, str):
            raise RuntimeError(
                f"container.resources.{key} must map string resource names"
            )
        result[resource_name] = _resource_quantity(quantity, key)
    return result


def _resource_quantity(
    value: object,
    key: str,
) -> KubernetesResourceQuantity:
    if isinstance(value, bool) or value is None:
        raise RuntimeError(
            f"container.resources.{key} values must be string or number quantities"
        )
    if isinstance(value, str | int | float):
        return value
    raise RuntimeError(
        f"container.resources.{key} values must be string or number quantities"
    )


def _container_resources(data: object) -> ContainerResources | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise RuntimeError("container.resources must be an object")
    resource_data = cast(Mapping[object, object], data)
    resources = ContainerResources(
        requests=_resource_quantity_map(resource_data, "requests"),
        limits=_resource_quantity_map(resource_data, "limits"),
        claims=_resource_claims(resource_data),
    )
    if (
        resources.requests is None
        and resources.limits is None
        and resources.claims is None
    ):
        return None
    return resources


def _resource_claims(
    data: Mapping[object, object],
) -> tuple[ContainerResourceClaim, ...] | None:
    value = data.get("claims")
    if value is None:
        return None
    if not isinstance(value, list):
        raise RuntimeError("container.resources.claims must be an array")
    claims: list[ContainerResourceClaim] = []
    for item in value:
        if not isinstance(item, dict):
            raise RuntimeError("container.resources.claims must contain objects")
        name = item.get("name")
        if not isinstance(name, str) or name == "":
            raise RuntimeError(
                "container.resources.claims.name must be a non-empty string"
            )
        request = item.get("request")
        if request is not None and not isinstance(request, str):
            raise RuntimeError("container.resources.claims.request must be a string")
        claims.append(ContainerResourceClaim(name=name, request=request))
    return tuple(claims)


def _lease_manifest(lease: LeaseResource) -> JsonObject:
    metadata = _metadata(lease.metadata)
    if lease.resource_version is not None:
        metadata["resourceVersion"] = lease.resource_version
    return {
        "apiVersion": "coordination.k8s.io/v1",
        "kind": "Lease",
        "metadata": metadata,
        "spec": {
            "holderIdentity": lease.spec.holder_identity,
            "acquireTime": _datetime_string(lease.spec.acquire_time),
            "renewTime": _datetime_string(lease.spec.renew_time),
            "leaseDurationSeconds": lease.spec.lease_duration_seconds,
            "leaseTransitions": lease.spec.lease_transitions,
        },
    }


def pod_resource(data: JsonObject) -> PodResource:
    spec = cast(JsonObject, data["spec"])
    status = cast(JsonObject | None, data.get("status"))
    return PodResource(
        metadata=_object_meta(data),
        spec=PodSpec(
            service_account_name=cast(str | None, spec.get("serviceAccountName")),
            automount_service_account_token=bool(
                spec.get("automountServiceAccountToken", True)
            ),
            image_pull_secrets=tuple(
                LocalObjectReference(name=str(item["name"]))
                for item in spec.get("imagePullSecrets", [])
            ),
            security_context=_pod_security_context(
                cast(JsonObject | None, spec.get("securityContext"))
            ),
            node_selector={
                str(key): str(value)
                for key, value in cast(
                    JsonObject,
                    spec.get("nodeSelector") or {},
                ).items()
            },
            tolerations=tuple(
                _toleration(cast(JsonObject, item))
                for item in spec.get("tolerations", [])
            ),
            dns_policy=cast(str | None, spec.get("dnsPolicy")),
            dns_config=_pod_dns_config(cast(JsonObject | None, spec.get("dnsConfig"))),
            host_aliases=tuple(
                HostAlias(
                    ip=str(item["ip"]),
                    hostnames=tuple(
                        str(hostname) for hostname in item.get("hostnames", [])
                    ),
                )
                for item in spec.get("hostAliases", [])
            ),
            containers=tuple(_container(item) for item in spec.get("containers", [])),
            volumes=tuple(_volume(item) for item in spec.get("volumes", [])),
        ),
        status=None if status is None else _pod_status(status),
    )


def _container(data: JsonObject) -> ContainerSpec:
    return ContainerSpec(
        name=str(data["name"]),
        image=str(data["image"]),
        command=(
            None
            if data.get("command") is None
            else tuple(str(item) for item in data["command"])
        ),
        args=tuple(str(item) for item in data.get("args", [])),
        working_dir=str(data.get("workingDir") or ""),
        resources=_container_resources(data.get("resources")),
        security_context=_container_security_context(
            cast(JsonObject, data.get("securityContext") or {})
        ),
        readiness_probe=_probe(cast(JsonObject | None, data.get("readinessProbe"))),
        env=tuple(
            EnvVar(name=str(item["name"]), value=str(item.get("value") or ""))
            for item in data.get("env", [])
        ),
        volume_mounts=tuple(
            VolumeMount(
                name=str(item["name"]),
                mount_path=str(item["mountPath"]),
                read_only=bool(item.get("readOnly", False)),
            )
            for item in data.get("volumeMounts", [])
        ),
    )


def _volume(
    data: JsonObject,
) -> PersistentVolumeClaimVolume | EmptyDirVolume | ConfigMapVolume | SecretVolume:
    persistent_volume_claim = cast(
        JsonObject | None,
        data.get("persistentVolumeClaim"),
    )
    if persistent_volume_claim is not None:
        return PersistentVolumeClaimVolume(
            name=str(data["name"]),
            claim_name=str(persistent_volume_claim["claimName"]),
        )
    empty_dir = cast(JsonObject | None, data.get("emptyDir"))
    if empty_dir is not None:
        return EmptyDirVolume(
            name=str(data["name"]),
            medium=cast(str | None, empty_dir.get("medium")),
            size_limit=cast(
                KubernetesResourceQuantity | None,
                empty_dir.get("sizeLimit"),
            ),
        )
    config_map = cast(JsonObject | None, data.get("configMap"))
    if config_map is not None:
        return ConfigMapVolume(
            name=str(data["name"]),
            config_map_name=str(config_map["name"]),
            items=_key_to_paths(config_map.get("items")),
            default_mode=_optional_int(config_map.get("defaultMode"), "defaultMode"),
        )
    secret = cast(JsonObject | None, data.get("secret"))
    if secret is not None:
        return SecretVolume(
            name=str(data["name"]),
            secret_name=str(secret["secretName"]),
            items=_key_to_paths(secret.get("items")),
            default_mode=_optional_int(secret.get("defaultMode"), "defaultMode"),
        )
    raise RuntimeError("unsupported Runtime Pod volume type")


def _key_to_paths(value: object) -> tuple[KeyToPath, ...]:
    if not isinstance(value, list) or not value:
        raise RuntimeError("selected ConfigMap and Secret volumes require items")
    items: list[KeyToPath] = []
    for item in value:
        if not isinstance(item, dict):
            raise RuntimeError("selected volume items must be objects")
        key = item.get("key")
        path = item.get("path")
        if not isinstance(key, str) or not key:
            raise RuntimeError("selected volume item key must be a non-empty string")
        if not isinstance(path, str) or not path:
            raise RuntimeError("selected volume item path must be a non-empty string")
        items.append(
            KeyToPath(
                key=key,
                path=path,
                mode=_optional_int(item.get("mode"), "mode"),
            )
        )
    return tuple(items)


def _optional_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"Pod volume {field} must be an integer")
    return value


def _pod_dns_config(data: JsonObject | None) -> PodDnsConfig | None:
    if data is None:
        return None
    return PodDnsConfig(
        nameservers=tuple(str(item) for item in data.get("nameservers", [])),
        searches=tuple(str(item) for item in data.get("searches", [])),
        options=tuple(
            PodDnsConfigOption(
                name=str(item["name"]),
                value=cast(str | None, item.get("value")),
            )
            for item in data.get("options", [])
        ),
    )


def _container_security_context(data: JsonObject) -> ContainerSecurityContext:
    capabilities = cast(JsonObject, data.get("capabilities") or {})
    return ContainerSecurityContext(
        privileged=bool(data.get("privileged", False)),
        allow_privilege_escalation=bool(data.get("allowPrivilegeEscalation", False)),
        read_only_root_filesystem=bool(data.get("readOnlyRootFilesystem", False)),
        run_as_non_root=bool(data.get("runAsNonRoot", False)),
        run_as_user=int(data.get("runAsUser") or 0),
        run_as_group=int(data.get("runAsGroup") or 0),
        capabilities_add=tuple(str(item) for item in capabilities.get("add", [])),
        capabilities_drop=tuple(str(item) for item in capabilities.get("drop", [])),
        proc_mount=cast(str | None, data.get("procMount")),
        seccomp_profile=_seccomp_profile(
            cast(JsonObject | None, data.get("seccompProfile"))
        ),
    )


def _seccomp_profile(data: JsonObject | None) -> SeccompProfile | None:
    if data is None:
        return None
    return SeccompProfile(
        profile_type=str(data["type"]),
        localhost_profile=cast(str | None, data.get("localhostProfile")),
    )


def _probe(data: JsonObject | None) -> Probe | None:
    if data is None:
        return None
    exec_action = cast(JsonObject | None, data.get("exec"))
    if exec_action is None:
        raise RuntimeError("Runtime container readiness probe must use exec")
    return Probe(
        exec_action=ExecAction(
            command=tuple(str(item) for item in exec_action.get("command", []))
        ),
        initial_delay_seconds=int(data.get("initialDelaySeconds") or 0),
        period_seconds=int(data.get("periodSeconds") or 0),
        timeout_seconds=int(data.get("timeoutSeconds") or 0),
        failure_threshold=int(data.get("failureThreshold") or 0),
    )


def _pod_security_context(data: JsonObject | None) -> PodSecurityContext | None:
    if data is None:
        return None
    run_as_user = data.get("runAsUser")
    run_as_group = data.get("runAsGroup")
    fs_group = data.get("fsGroup")
    fs_group_change_policy = data.get("fsGroupChangePolicy")
    if fs_group is None or fs_group_change_policy is None:
        return None
    return PodSecurityContext(
        run_as_user=None if run_as_user is None else int(run_as_user),
        run_as_group=None if run_as_group is None else int(run_as_group),
        fs_group=int(fs_group),
        fs_group_change_policy=str(fs_group_change_policy),
    )


def _toleration(data: JsonObject) -> Toleration:
    return Toleration(
        key=cast(str | None, data.get("key")),
        operator=cast(str | None, data.get("operator")),
        value=cast(str | None, data.get("value")),
        effect=cast(str | None, data.get("effect")),
        toleration_seconds=cast(int | None, data.get("tolerationSeconds")),
    )


def _pod_status(status: JsonObject) -> PodStatus:
    conditions = status.get("conditions") or []
    ready_condition = next(
        (
            item
            for item in cast(list[JsonObject], conditions)
            if item.get("type") == "Ready"
        ),
        None,
    )
    ready = ready_condition is not None and ready_condition.get("status") == "True"
    waiting_reason = _first_waiting_reason(
        cast(list[JsonObject], status.get("containerStatuses") or [])
    )
    termination_evidence = _first_termination_evidence(
        cast(list[JsonObject], status.get("containerStatuses") or [])
    )
    return PodStatus(
        phase=cast(str | None, status.get("phase")),
        ready=ready,
        ready_reason=(
            None
            if ready_condition is None
            else cast(str | None, ready_condition.get("reason"))
        ),
        waiting_reason=waiting_reason,
        termination_evidence=termination_evidence,
    )


def _first_waiting_reason(container_statuses: list[JsonObject]) -> str | None:
    for item in container_statuses:
        state = cast(JsonObject, item.get("state") or {})
        waiting = cast(JsonObject | None, state.get("waiting"))
        if waiting is None:
            continue
        reason = waiting.get("reason")
        if isinstance(reason, str) and reason:
            return reason
    return None


def _first_termination_evidence(
    container_statuses: list[JsonObject],
) -> ContainerTerminationEvidence | None:
    for item in container_statuses:
        state = cast(JsonObject, item.get("state") or {})
        terminated = cast(JsonObject | None, state.get("terminated"))
        if terminated is None:
            continue
        name = item.get("name")
        exit_code = terminated.get("exitCode")
        if not isinstance(name, str) or not name:
            raise RuntimeError("container status name must be a non-empty string")
        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            raise RuntimeError("terminated container exitCode must be an integer")
        reason = terminated.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise RuntimeError("terminated container reason must be a string")
        return ContainerTerminationEvidence(
            container_name=name,
            exit_code=exit_code,
            reason=reason,
            oom_killed=reason == "OOMKilled",
        )
    return None


def _pvc_resource(data: JsonObject) -> PersistentVolumeClaimResource:
    spec = cast(JsonObject, data["spec"])
    resources = cast(JsonObject, spec.get("resources") or {})
    requests = cast(JsonObject, resources.get("requests") or {})
    return PersistentVolumeClaimResource(
        metadata=_object_meta(data),
        spec=PersistentVolumeClaimSpec(
            storage_class_name=str(spec.get("storageClassName") or ""),
            access_modes=tuple(str(item) for item in spec.get("accessModes", [])),
            storage_request=str(requests.get("storage") or ""),
        ),
    )


def service_resource(data: JsonObject) -> ServiceResource:
    """Parse one Provider-owned Service."""
    spec = cast(JsonObject, data["spec"])
    cluster_ip = spec.get("clusterIP")
    if cluster_ip is not None and not isinstance(cluster_ip, str):
        raise RuntimeError("Service clusterIP must be a string")
    return ServiceResource(
        metadata=_object_meta(data),
        spec=ServiceSpec(
            service_type=str(spec.get("type") or "ClusterIP"),
            cluster_ip=cluster_ip,
            selector={
                str(key): str(value)
                for key, value in cast(JsonObject, spec.get("selector") or {}).items()
            },
            ports=tuple(
                ServicePort(
                    name=cast(str | None, item.get("name")),
                    protocol=str(item.get("protocol") or "TCP"),
                    port=_required_int(item.get("port"), "Service port"),
                    target_port=_service_target_port(item.get("targetPort")),
                )
                for item in spec.get("ports", [])
            ),
        ),
    )


def config_map_resource(data: JsonObject) -> ConfigMapResource:
    """Parse one Provider-owned ConfigMap."""
    return ConfigMapResource(
        metadata=_object_meta(data),
        data={
            str(key): str(value)
            for key, value in cast(JsonObject, data.get("data") or {}).items()
        },
        immutable=_optional_bool(data.get("immutable"), "ConfigMap immutable"),
    )


def secret_resource(data: JsonObject) -> SecretResource:
    """Parse one Provider-owned Secret into opaque byte values."""
    encoded = cast(JsonObject, data.get("data") or {})
    decoded: dict[str, bytes] = {}
    for key, value in encoded.items():
        if not isinstance(value, str):
            raise RuntimeError("Secret data values must be base64 strings")
        try:
            decoded[str(key)] = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as error:
            raise RuntimeError("Secret data contains invalid base64") from error
    return SecretResource(
        metadata=_object_meta(data),
        data=decoded,
        secret_type=str(data.get("type") or "Opaque"),
        immutable=_optional_bool(data.get("immutable"), "Secret immutable"),
    )


def _required_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"{field} must be an integer")
    return value


def _service_target_port(value: object) -> int | str:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise RuntimeError("Service targetPort must be an integer or named port")
    return value


def _optional_bool(value: object, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise RuntimeError(f"{field} must be a boolean")
    return value


def network_policy_resource(data: JsonObject) -> NetworkPolicyResource:
    """Parse one Provider-owned Runtime NetworkPolicy."""
    spec = cast(JsonObject, data["spec"])
    return NetworkPolicyResource(
        metadata=_object_meta(data),
        spec=NetworkPolicySpec(
            pod_selector=_label_selector_resource(
                cast(JsonObject, spec.get("podSelector") or {})
            ),
            policy_types=tuple(str(item) for item in spec.get("policyTypes", [])),
            ingress=tuple(
                _network_policy_ingress_rule(cast(JsonObject, item))
                for item in spec.get("ingress", [])
            ),
            egress=tuple(
                _network_policy_egress_rule(cast(JsonObject, item))
                for item in spec.get("egress", [])
            ),
        ),
    )


def _network_policy_egress_rule(data: JsonObject) -> NetworkPolicyEgressRule:
    return NetworkPolicyEgressRule(
        peers=tuple(
            _network_policy_peer(cast(JsonObject, item)) for item in data.get("to", [])
        ),
        ports=tuple(
            NetworkPolicyPort(
                protocol=str(item.get("protocol") or "TCP"),
                port=_network_policy_port_value(item["port"]),
            )
            for item in data.get("ports", [])
        ),
    )


def _network_policy_ingress_rule(data: JsonObject) -> NetworkPolicyIngressRule:
    return NetworkPolicyIngressRule(
        peers=tuple(
            _network_policy_peer(cast(JsonObject, item))
            for item in data.get("from", [])
        ),
        ports=tuple(
            NetworkPolicyPort(
                protocol=str(item.get("protocol") or "TCP"),
                port=_network_policy_port_value(item["port"]),
            )
            for item in data.get("ports", [])
        ),
    )


def _network_policy_port_value(value: object) -> int | str:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValueError("NetworkPolicy port must be an integer or named port")
    return value


def _network_policy_peer(data: JsonObject) -> NetworkPolicyPeer:
    ip_block = cast(JsonObject | None, data.get("ipBlock"))
    return NetworkPolicyPeer(
        namespace_selector=(
            None
            if data.get("namespaceSelector") is None
            else _label_selector_resource(cast(JsonObject, data["namespaceSelector"]))
        ),
        pod_selector=(
            None
            if data.get("podSelector") is None
            else _label_selector_resource(cast(JsonObject, data["podSelector"]))
        ),
        ip_block=(
            None
            if ip_block is None
            else IpBlock(
                cidr=str(ip_block["cidr"]),
                except_cidrs=tuple(str(item) for item in ip_block.get("except", [])),
            )
        ),
    )


def _label_selector_resource(data: JsonObject) -> LabelSelector:
    return LabelSelector(
        match_labels={
            str(key): str(value)
            for key, value in cast(
                JsonObject,
                data.get("matchLabels") or {},
            ).items()
        },
        match_expressions=tuple(
            _label_selector_requirement(cast(JsonObject, item))
            for item in data.get("matchExpressions", [])
        ),
    )


def _label_selector_requirement(data: JsonObject) -> LabelSelectorRequirement:
    key = data.get("key")
    operator = data.get("operator")
    values = data.get("values", [])
    if not isinstance(key, str) or not key:
        raise RuntimeError("label selector requirement key must be a non-empty string")
    if operator not in {"In", "NotIn", "Exists", "DoesNotExist"}:
        raise RuntimeError("label selector requirement operator is unsupported")
    if not isinstance(values, list) or any(
        not isinstance(item, str) for item in values
    ):
        raise RuntimeError("label selector requirement values must be strings")
    if operator in {"In", "NotIn"} and not values:
        raise RuntimeError("set-based label selector requirements need values")
    if operator in {"Exists", "DoesNotExist"} and values:
        raise RuntimeError("existence label selector requirements cannot have values")
    return LabelSelectorRequirement(
        key=key,
        operator=operator,
        values=tuple(values),
    )


def _lease_resource(data: JsonObject) -> LeaseResource:
    spec = cast(JsonObject, data["spec"])
    metadata = cast(JsonObject, data.get("metadata") or {})
    return LeaseResource(
        metadata=_object_meta(data),
        spec=LeaseSpec(
            holder_identity=cast(str | None, spec.get("holderIdentity")),
            acquire_time=_parse_datetime(cast(str | None, spec.get("acquireTime"))),
            renew_time=_parse_datetime(cast(str | None, spec.get("renewTime"))),
            lease_duration_seconds=int(spec.get("leaseDurationSeconds") or 0),
            lease_transitions=int(spec.get("leaseTransitions") or 0),
        ),
        resource_version=cast(str | None, metadata.get("resourceVersion")),
    )


def _object_meta(data: JsonObject) -> ObjectMeta:
    metadata = cast(JsonObject, data["metadata"])
    return ObjectMeta(
        name=str(metadata["name"]),
        namespace=str(metadata["namespace"]),
        labels=cast(Mapping[str, str], metadata.get("labels") or {}),
        annotations=cast(Mapping[str, str], metadata.get("annotations") or {}),
        deletion_timestamp=_parse_datetime(
            cast(str | None, metadata.get("deletionTimestamp"))
        ),
    )


def _label_selector(labels: Mapping[str, str]) -> str:
    return ",".join(f"{key}={value}" for key, value in sorted(labels.items()))


def _datetime_string(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
