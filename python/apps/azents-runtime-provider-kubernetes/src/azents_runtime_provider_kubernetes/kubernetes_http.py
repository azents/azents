"""In-cluster Kubernetes HTTP adapter for Runtime Provider resources."""

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
    ContainerResourceClaim,
    ContainerResources,
    ContainerSpec,
    EnvVar,
    KubernetesApi,
    KubernetesResourceQuantity,
    LeaseResource,
    LeaseSpec,
    LocalObjectReference,
    ObjectMeta,
    PersistentVolumeClaimResource,
    PersistentVolumeClaimSpec,
    PersistentVolumeClaimVolume,
    PodResource,
    PodSecurityContext,
    PodSpec,
    PodStatus,
    PodWatchEvent,
    Toleration,
    VolumeMount,
)

_SERVICE_ACCOUNT_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
_TOKEN_PATH = _SERVICE_ACCOUNT_DIR / "token"
_CA_CERT_PATH = _SERVICE_ACCOUNT_DIR / "ca.crt"
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

    async def get_pod(self, name: str, namespace: str) -> PodResource | None:
        data = await self._request_json(
            "GET",
            f"/api/v1/namespaces/{namespace}/pods/{name}",
            allow_not_found=True,
        )
        return None if data is None else pod_resource(data)

    async def apply_pod(self, pod: PodResource) -> None:
        await self._create_or_patch(
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
        await self._create_or_patch(
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

    async def get_lease(self, name: str, namespace: str) -> LeaseResource | None:
        data = await self._request_json(
            "GET",
            f"/apis/coordination.k8s.io/v1/namespaces/{namespace}/leases/{name}",
            allow_not_found=True,
        )
        return None if data is None else _lease_resource(data)

    async def apply_lease(self, lease: LeaseResource) -> None:
        await self._create_or_patch(
            (
                f"/apis/coordination.k8s.io/v1/namespaces/"
                f"{lease.metadata.namespace}/leases/{lease.metadata.name}"
            ),
            (
                f"/apis/coordination.k8s.io/v1/namespaces/"
                f"{lease.metadata.namespace}/leases"
            ),
            _lease_manifest(lease),
        )

    async def _create_or_patch(
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


def pod_manifest(pod: PodResource) -> JsonObject:
    spec: JsonObject = {
        "automountServiceAccountToken": pod.spec.automount_service_account_token,
        "containers": [
            _container_manifest(container) for container in pod.spec.containers
        ],
        "volumes": [
            {
                "name": volume.name,
                "persistentVolumeClaim": {"claimName": volume.claim_name},
            }
            for volume in pod.spec.volumes
        ],
    }
    if pod.spec.service_account_name is not None:
        spec["serviceAccountName"] = pod.spec.service_account_name
    if pod.spec.image_pull_secrets:
        spec["imagePullSecrets"] = [
            {"name": secret.name} for secret in pod.spec.image_pull_secrets
        ]
    if pod.spec.security_context is not None:
        spec["securityContext"] = {
            "runAsUser": pod.spec.security_context.run_as_user,
            "runAsGroup": pod.spec.security_context.run_as_group,
            "fsGroup": pod.spec.security_context.fs_group,
            "fsGroupChangePolicy": pod.spec.security_context.fs_group_change_policy,
        }
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
                }.items()
                if value is not None
            }
            for toleration in pod.spec.tolerations
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
        "workingDir": container.working_dir,
        "env": [{"name": item.name, "value": item.value} for item in container.env],
        "volumeMounts": [
            {"name": item.name, "mountPath": item.mount_path}
            for item in container.volume_mounts
        ],
    }
    if container.resources is not None:
        manifest["resources"] = _container_resources_manifest(container.resources)
    return manifest


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
    resources = ContainerResources(
        requests=_resource_quantity_map(data, "requests"),
        limits=_resource_quantity_map(data, "limits"),
        claims=_resource_claims(data),
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
    return {
        "apiVersion": "coordination.k8s.io/v1",
        "kind": "Lease",
        "metadata": _metadata(lease.metadata),
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
            containers=tuple(_container(item) for item in spec.get("containers", [])),
            volumes=tuple(_volume(item) for item in spec.get("volumes", [])),
        ),
        status=None if status is None else _pod_status(status),
    )


def _container(data: JsonObject) -> ContainerSpec:
    return ContainerSpec(
        name=str(data["name"]),
        image=str(data["image"]),
        working_dir=str(data.get("workingDir") or ""),
        resources=_container_resources(data.get("resources")),
        env=tuple(
            EnvVar(name=str(item["name"]), value=str(item.get("value") or ""))
            for item in data.get("env", [])
        ),
        volume_mounts=tuple(
            VolumeMount(name=str(item["name"]), mount_path=str(item["mountPath"]))
            for item in data.get("volumeMounts", [])
        ),
    )


def _volume(data: JsonObject) -> PersistentVolumeClaimVolume:
    return PersistentVolumeClaimVolume(
        name=str(data["name"]),
        claim_name=str(cast(JsonObject, data["persistentVolumeClaim"])["claimName"]),
    )


def _pod_security_context(data: JsonObject | None) -> PodSecurityContext | None:
    if data is None:
        return None
    run_as_user = data.get("runAsUser")
    run_as_group = data.get("runAsGroup")
    fs_group = data.get("fsGroup")
    fs_group_change_policy = data.get("fsGroupChangePolicy")
    if (
        run_as_user is None
        or run_as_group is None
        or fs_group is None
        or fs_group_change_policy is None
    ):
        return None
    return PodSecurityContext(
        run_as_user=int(run_as_user),
        run_as_group=int(run_as_group),
        fs_group=int(fs_group),
        fs_group_change_policy=str(fs_group_change_policy),
    )


def _toleration(data: JsonObject) -> Toleration:
    return Toleration(
        key=cast(str | None, data.get("key")),
        operator=cast(str | None, data.get("operator")),
        value=cast(str | None, data.get("value")),
        effect=cast(str | None, data.get("effect")),
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
    return PodStatus(
        phase=cast(str | None, status.get("phase")),
        ready=ready,
        ready_reason=(
            None
            if ready_condition is None
            else cast(str | None, ready_condition.get("reason"))
        ),
        waiting_reason=waiting_reason,
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
