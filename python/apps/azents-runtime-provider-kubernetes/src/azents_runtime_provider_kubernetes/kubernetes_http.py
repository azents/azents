"""SDK-backed Kubernetes resource boundary for Runtime Provider resources."""

import asyncio
import base64
import binascii
import dataclasses
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Self

import aiohttp
from kubernetes_asyncio import client, config, watch
from kubernetes_asyncio.client.exceptions import ApiException

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

POD_WATCH_TIMEOUT = aiohttp.ClientTimeout(
    total=None,
    sock_connect=30,
    sock_read=None,
)

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
class KubernetesResourceOperations:
    """Public SDK operations for one namespaced Kubernetes resource kind."""

    read: Callable[..., Awaitable[object]]
    list: Callable[..., Awaitable[object]]
    create: Callable[..., Awaitable[object]]
    replace: Callable[..., Awaitable[object]]
    patch: Callable[..., Awaitable[object]]
    delete: Callable[..., Awaitable[object]]


class ProviderPodWatch(watch.Watch):
    """Preserve Provider Status validation through the public SDK decoder hook."""

    def unmarshal_event(self, data: str | bytes, response_type: str | None) -> object:
        """Validate Status errors while the SDK owns transport and reconnects."""
        event = _decode_json_object(json.loads(data))
        if event.get("type") == "ERROR":
            status = _required_object(event.get("object"), "watch Status")
            code = _required_int(status.get("code"), "watch Status code")
            if status.get("kind") != "Status" or not 400 <= code <= 599:
                raise RuntimeError("Kubernetes watch Status is malformed")
            reason = _optional_string(status.get("reason"), "watch Status reason")
            message = _optional_string(status.get("message"), "watch Status message")
            error = ApiException(status=code, reason=reason)
            error.body = (
                message
                if message is not None
                else "Kubernetes Pod watch returned a Status error"
            ).encode()
            raise error
        return super().unmarshal_event(data, response_type)


class KubernetesHttpApi(KubernetesApi):
    """Typed Provider boundary backed by public Kubernetes SDK operations."""

    def __init__(
        self,
        sdk: client.ApiClient,
        core: client.CoreV1Api,
        networking: client.NetworkingV1Api,
        coordination: client.CoordinationV1Api,
        authorization: client.AuthorizationV1Api,
        apis: client.ApisApi,
    ) -> None:
        self.sdk = sdk
        self.core = core
        self.networking = networking
        self.coordination = coordination
        self.authorization = authorization
        self.apis = apis
        self.pods = KubernetesResourceOperations(
            read=core.read_namespaced_pod,
            list=core.list_namespaced_pod,
            create=core.create_namespaced_pod,
            replace=core.replace_namespaced_pod,
            patch=core.patch_namespaced_pod,
            delete=core.delete_namespaced_pod,
        )
        self.pvcs = KubernetesResourceOperations(
            read=core.read_namespaced_persistent_volume_claim,
            list=core.list_namespaced_persistent_volume_claim,
            create=core.create_namespaced_persistent_volume_claim,
            replace=core.replace_namespaced_persistent_volume_claim,
            patch=core.patch_namespaced_persistent_volume_claim,
            delete=core.delete_namespaced_persistent_volume_claim,
        )
        self.services = KubernetesResourceOperations(
            read=core.read_namespaced_service,
            list=core.list_namespaced_service,
            create=core.create_namespaced_service,
            replace=core.replace_namespaced_service,
            patch=core.patch_namespaced_service,
            delete=core.delete_namespaced_service,
        )
        self.config_maps = KubernetesResourceOperations(
            read=core.read_namespaced_config_map,
            list=core.list_namespaced_config_map,
            create=core.create_namespaced_config_map,
            replace=core.replace_namespaced_config_map,
            patch=core.patch_namespaced_config_map,
            delete=core.delete_namespaced_config_map,
        )
        self.secrets = KubernetesResourceOperations(
            read=core.read_namespaced_secret,
            list=core.list_namespaced_secret,
            create=core.create_namespaced_secret,
            replace=core.replace_namespaced_secret,
            patch=core.patch_namespaced_secret,
            delete=core.delete_namespaced_secret,
        )
        self.network_policies = KubernetesResourceOperations(
            read=networking.read_namespaced_network_policy,
            list=networking.list_namespaced_network_policy,
            create=networking.create_namespaced_network_policy,
            replace=networking.replace_namespaced_network_policy,
            patch=networking.patch_namespaced_network_policy,
            delete=networking.delete_namespaced_network_policy,
        )

    @classmethod
    async def from_in_cluster(cls) -> Self:
        """Compose SDK clients using SDK-owned ServiceAccount auth and TLS."""
        configuration = client.Configuration()
        config.load_incluster_config(client_configuration=configuration)
        sdk = client.ApiClient(configuration=configuration)
        return cls(
            sdk=sdk,
            core=client.CoreV1Api(sdk),
            networking=client.NetworkingV1Api(sdk),
            coordination=client.CoordinationV1Api(sdk),
            authorization=client.AuthorizationV1Api(sdk),
            apis=client.ApisApi(sdk),
        )

    async def close(self) -> None:
        """Close the SDK client and its token-refresh/session resources."""
        await self.sdk.close()

    async def _request(
        self,
        operation: Awaitable[object],
        *,
        allow_not_found: bool,
        method: str,
        resource: str,
    ) -> JsonObject | None:
        """Translate SDK outcomes only at the typed Provider ingress boundary."""
        try:
            result = await operation
        except ApiException as error:
            if error.status == 404 and allow_not_found:
                return None
            raise KubernetesApiRequestError(
                method=method,
                path=resource,
                status=error.status,
                reason=error.reason,
                body=_api_error_body(error.body),
            ) from error
        if result is None:
            return None
        return _decode_json_object(self.sdk.sanitize_for_serialization(result))

    async def discover_api_resources(self, api_version: str) -> frozenset[str]:
        """Return resources for the API versions used by Provider diagnostics."""
        match api_version:
            case "v1":
                operation = self.core.get_api_resources()
            case "networking.k8s.io/v1":
                operation = self.networking.get_api_resources()
            case "coordination.k8s.io/v1":
                operation = self.coordination.get_api_resources()
            case "authorization.k8s.io/v1":
                operation = self.authorization.get_api_resources()
            case _:
                raise ValueError(f"Unsupported Provider API version: {api_version}")
        data = await self._request(
            operation, allow_not_found=False, method="GET", resource=api_version
        )
        if data is None:
            return frozenset()
        resources = _object_list(data.get("resources") or [], "resources")
        return frozenset(
            item["name"]
            for item in resources
            if isinstance(item.get("name"), str) and "/" not in item["name"]
        )

    async def list_api_groups(self) -> frozenset[str]:
        """Return group names using SDK-owned API discovery."""
        data = await self._request(
            self.apis.get_api_versions(),
            allow_not_found=False,
            method="GET",
            resource="API groups",
        )
        if data is None:
            return frozenset()
        groups = _object_list(data.get("groups") or [], "groups")
        return frozenset(
            item["name"] for item in groups if isinstance(item.get("name"), str)
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
        """Evaluate one exact permission with the SDK access-review API."""
        body = client.V1SelfSubjectAccessReview(
            api_version="authorization.k8s.io/v1",
            kind="SelfSubjectAccessReview",
            spec=client.V1SelfSubjectAccessReviewSpec(
                resource_attributes=client.V1ResourceAttributes(
                    group=api_group,
                    resource=resource,
                    verb=verb,
                    namespace=namespace,
                    name=resource_name,
                ),
            ),
        )
        data = await self._request(
            self.authorization.create_self_subject_access_review(body=body),
            allow_not_found=False,
            method="POST",
            resource="SelfSubjectAccessReview",
        )
        if data is None:
            return False
        return (
            _required_object(data.get("status") or {}, "status").get("allowed") is True
        )

    async def get_namespace(self, name: str) -> NamespaceResource | None:
        data = await self._request(
            self.core.read_namespace(name=name),
            allow_not_found=True,
            method="GET",
            resource="Namespace",
        )
        if data is None:
            return None
        metadata = _required_object(data["metadata"], "metadata")
        return NamespaceResource(
            name=str(metadata["name"]),
            labels=_string_mapping(metadata.get("labels") or {}, "metadata.labels"),
        )

    async def _get(
        self,
        operations: KubernetesResourceOperations,
        name: str,
        namespace: str,
    ) -> JsonObject | None:
        return await self._request(
            operations.read(name=name, namespace=namespace),
            allow_not_found=True,
            method="GET",
            resource=name,
        )

    async def _list(
        self,
        operations: KubernetesResourceOperations,
        labels: Mapping[str, str],
        namespace: str,
    ) -> list[JsonObject]:
        data = await self._request(
            operations.list(
                namespace=namespace, label_selector=_label_selector(labels)
            ),
            allow_not_found=False,
            method="GET",
            resource=namespace,
        )
        return _object_list(
            _required_object(data, "list response").get("items"), "items"
        )

    async def _delete(
        self,
        operations: KubernetesResourceOperations,
        name: str,
        namespace: str,
        *,
        body: client.V1DeleteOptions | None,
    ) -> None:
        await self._request(
            operations.delete(name=name, namespace=namespace, body=body),
            allow_not_found=True,
            method="DELETE",
            resource=name,
        )

    async def _apply(
        self,
        operations: KubernetesResourceOperations,
        metadata: ObjectMeta,
        manifest: JsonObject,
        *,
        replace: bool,
    ) -> None:
        for attempt in range(2 if replace else 1):
            existing = await self._get(operations, metadata.name, metadata.namespace)
            try:
                if existing is None:
                    await self._request(
                        operations.create(namespace=metadata.namespace, body=manifest),
                        allow_not_found=False,
                        method="POST",
                        resource=metadata.name,
                    )
                elif replace:
                    await self._request(
                        operations.replace(
                            name=metadata.name,
                            namespace=metadata.namespace,
                            body=_replacement_manifest(manifest, existing),
                        ),
                        allow_not_found=False,
                        method="PUT",
                        resource=metadata.name,
                    )
                else:
                    await self._request(
                        operations.patch(
                            name=metadata.name,
                            namespace=metadata.namespace,
                            body=manifest,
                            _content_type="application/merge-patch+json",
                        ),
                        allow_not_found=False,
                        method="PATCH",
                        resource=metadata.name,
                    )
                return
            except KubernetesApiRequestError as error:
                if not replace or error.status != 409 or attempt == 1:
                    raise
        raise AssertionError("Kubernetes resource replacement retry exhausted")

    async def get_pod(self, name: str, namespace: str) -> PodResource | None:
        data = await self._get(self.pods, name, namespace)
        return None if data is None else pod_resource(data)

    async def apply_pod(self, pod: PodResource) -> None:
        await self._apply(self.pods, pod.metadata, pod_manifest(pod), replace=False)

    async def delete_pod(
        self,
        name: str,
        namespace: str,
        *,
        grace_period_seconds: int | None = None,
    ) -> None:
        body = (
            None
            if grace_period_seconds is None
            else client.V1DeleteOptions(
                api_version="v1",
                kind="DeleteOptions",
                grace_period_seconds=grace_period_seconds,
            )
        )
        await self._delete(self.pods, name, namespace, body=body)

    async def list_pods(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> Sequence[PodResource]:
        return tuple(
            pod_resource(item)
            for item in await self._list(self.pods, labels, namespace)
        )

    async def watch_pods(
        self,
        labels: Mapping[str, str],
        namespace: str,
    ) -> AsyncIterator[PodWatchEvent]:
        try:
            async with ProviderPodWatch() as watcher:
                async for value in watcher.stream(
                    self.core.list_namespaced_pod,
                    namespace=namespace,
                    label_selector=_label_selector(labels),
                    allow_watch_bookmarks=True,
                    _request_timeout=POD_WATCH_TIMEOUT,
                ):
                    if not isinstance(value, dict):
                        raise RuntimeError(
                            "Kubernetes SDK watch event must be an object"
                        )
                    event_type = str(value.get("type") or "")
                    if event_type == "BOOKMARK":
                        continue
                    pod = _optional_object(value.get("raw_object"), "watch object")
                    if pod is not None:
                        yield PodWatchEvent(
                            event_type=event_type, pod=pod_resource(pod)
                        )
        except asyncio.CancelledError:
            raise
        except ApiException as error:
            code = _required_int(error.status, "watch Status code")
            if not 400 <= code <= 599:
                raise RuntimeError("Kubernetes watch Status is malformed") from error
            raise KubernetesApiRequestError(
                method="GET",
                path="Pod watch",
                status=code,
                reason=error.reason,
                body=_api_error_body(error.body),
            ) from error

    async def get_pvc(
        self, name: str, namespace: str
    ) -> PersistentVolumeClaimResource | None:
        data = await self._get(self.pvcs, name, namespace)
        return None if data is None else _pvc_resource(data)

    async def apply_pvc(self, pvc: PersistentVolumeClaimResource) -> None:
        await self._apply(self.pvcs, pvc.metadata, _pvc_manifest(pvc), replace=False)

    async def delete_pvc(self, name: str, namespace: str) -> None:
        await self._delete(self.pvcs, name, namespace, body=None)

    async def list_pvcs(
        self, labels: Mapping[str, str], namespace: str
    ) -> Sequence[PersistentVolumeClaimResource]:
        return tuple(
            _pvc_resource(item)
            for item in await self._list(self.pvcs, labels, namespace)
        )

    async def get_service(self, name: str, namespace: str) -> ServiceResource | None:
        data = await self._get(self.services, name, namespace)
        return None if data is None else service_resource(data)

    async def apply_service(self, service: ServiceResource) -> None:
        await self._apply(
            self.services, service.metadata, service_manifest(service), replace=False
        )

    async def delete_service(self, name: str, namespace: str) -> None:
        await self._delete(self.services, name, namespace, body=None)

    async def list_services(
        self, labels: Mapping[str, str], namespace: str
    ) -> Sequence[ServiceResource]:
        return tuple(
            service_resource(item)
            for item in await self._list(self.services, labels, namespace)
        )

    async def get_config_map(
        self, name: str, namespace: str
    ) -> ConfigMapResource | None:
        data = await self._get(self.config_maps, name, namespace)
        return None if data is None else config_map_resource(data)

    async def apply_config_map(self, config_map: ConfigMapResource) -> None:
        await self._apply(
            self.config_maps,
            config_map.metadata,
            config_map_manifest(config_map),
            replace=False,
        )

    async def delete_config_map(self, name: str, namespace: str) -> None:
        await self._delete(self.config_maps, name, namespace, body=None)

    async def list_config_maps(
        self, labels: Mapping[str, str], namespace: str
    ) -> Sequence[ConfigMapResource]:
        return tuple(
            config_map_resource(item)
            for item in await self._list(self.config_maps, labels, namespace)
        )

    async def get_secret(self, name: str, namespace: str) -> SecretResource | None:
        data = await self._get(self.secrets, name, namespace)
        return None if data is None else secret_resource(data)

    async def apply_secret(self, secret: SecretResource) -> None:
        await self._apply(
            self.secrets, secret.metadata, secret_manifest(secret), replace=False
        )

    async def delete_secret(self, name: str, namespace: str) -> None:
        await self._delete(self.secrets, name, namespace, body=None)

    async def list_secrets(
        self, labels: Mapping[str, str], namespace: str
    ) -> Sequence[SecretResource]:
        return tuple(
            secret_resource(item)
            for item in await self._list(self.secrets, labels, namespace)
        )

    async def get_network_policy(
        self, name: str, namespace: str
    ) -> NetworkPolicyResource | None:
        data = await self._get(self.network_policies, name, namespace)
        return None if data is None else network_policy_resource(data)

    async def apply_network_policy(self, network_policy: NetworkPolicyResource) -> None:
        await self._apply(
            self.network_policies,
            network_policy.metadata,
            network_policy_manifest(network_policy),
            replace=True,
        )

    async def delete_network_policy(self, name: str, namespace: str) -> None:
        await self._delete(self.network_policies, name, namespace, body=None)

    async def list_network_policies(
        self, labels: Mapping[str, str], namespace: str
    ) -> Sequence[NetworkPolicyResource]:
        return tuple(
            network_policy_resource(item)
            for item in await self._list(self.network_policies, labels, namespace)
        )

    async def get_lease(self, name: str, namespace: str) -> LeaseResource | None:
        data = await self._request(
            self.coordination.read_namespaced_lease(name=name, namespace=namespace),
            allow_not_found=True,
            method="GET",
            resource=name,
        )
        return None if data is None else _lease_resource(data)

    async def apply_lease(self, lease: LeaseResource) -> None:
        body = client.V1Lease(
            api_version="coordination.k8s.io/v1",
            kind="Lease",
            metadata=client.V1ObjectMeta(
                name=lease.metadata.name,
                namespace=lease.metadata.namespace,
                labels=dict(lease.metadata.labels),
                annotations=dict(lease.metadata.annotations),
                resource_version=lease.resource_version,
            ),
            spec=client.V1LeaseSpec(
                holder_identity=lease.spec.holder_identity,
                acquire_time=lease.spec.acquire_time,
                renew_time=lease.spec.renew_time,
                lease_duration_seconds=lease.spec.lease_duration_seconds,
                lease_transitions=lease.spec.lease_transitions,
            ),
        )
        try:
            if lease.resource_version is None:
                await self._request(
                    self.coordination.create_namespaced_lease(
                        namespace=lease.metadata.namespace, body=body
                    ),
                    allow_not_found=False,
                    method="POST",
                    resource=lease.metadata.name,
                )
            else:
                await self._request(
                    self.coordination.replace_namespaced_lease(
                        name=lease.metadata.name,
                        namespace=lease.metadata.namespace,
                        body=body,
                    ),
                    allow_not_found=False,
                    method="PUT",
                    resource=lease.metadata.name,
                )
        except KubernetesApiRequestError as error:
            if error.status == 409:
                raise LeaseConflictError() from error
            raise


def _api_error_body(value: object) -> str:
    """Normalize SDK error evidence without hiding non-text body bugs."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    raise TypeError("Kubernetes SDK error body must be text or bytes")


def _decode_json_object(value: object) -> JsonObject:
    if not isinstance(value, dict):
        raise RuntimeError("Kubernetes API JSON response must be an object")
    result: JsonObject = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise RuntimeError("Kubernetes API JSON object keys must be strings")
        result[key] = _decode_json_value(item)
    return result


def _decode_json_value(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [_decode_json_value(item) for item in value]
    if isinstance(value, dict):
        return _decode_json_object(value)
    raise RuntimeError("Kubernetes API response contains a non-JSON value")


def _required_object(value: object, field: str) -> JsonObject:
    if not isinstance(value, dict):
        raise RuntimeError(f"{field} must be an object")
    return value


def _optional_object(value: object, field: str) -> JsonObject | None:
    if value is None:
        return None
    return _required_object(value, field)


def _object_list(value: object, field: str) -> list[JsonObject]:
    if not isinstance(value, list):
        raise RuntimeError(f"{field} must be an array")
    result: list[JsonObject] = []
    for item in value:
        result.append(_required_object(item, f"{field} item"))
    return result


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"{field} must be a string")
    return value


def _optional_quantity(
    value: object,
    field: str,
) -> KubernetesResourceQuantity | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        raise RuntimeError(f"{field} must be a string or number")
    return value


def _string_mapping(value: object, field: str) -> dict[str, str]:
    data = _required_object(value, field)
    result: dict[str, str] = {}
    for key, item in data.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise RuntimeError(f"{field} must map strings to strings")
        result[key] = item
    return result


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
    resource_data = data
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
    spec = _required_object(data["spec"], "spec")
    status = _optional_object(data.get("status"), "status")
    return PodResource(
        metadata=_object_meta(data),
        spec=PodSpec(
            service_account_name=_optional_string(
                spec.get("serviceAccountName"), "serviceAccountName"
            ),
            automount_service_account_token=bool(
                spec.get("automountServiceAccountToken", True)
            ),
            image_pull_secrets=tuple(
                LocalObjectReference(name=str(item["name"]))
                for item in spec.get("imagePullSecrets", [])
            ),
            security_context=_pod_security_context(
                _optional_object(spec.get("securityContext"), "securityContext")
            ),
            node_selector=_string_mapping(
                spec.get("nodeSelector") or {},
                "nodeSelector",
            ),
            tolerations=tuple(
                _toleration(_required_object(item, "array item"))
                for item in spec.get("tolerations", [])
            ),
            dns_policy=_optional_string(spec.get("dnsPolicy"), "dnsPolicy"),
            dns_config=_pod_dns_config(
                _optional_object(spec.get("dnsConfig"), "dnsConfig")
            ),
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
            _required_object(data.get("securityContext") or {}, "securityContext")
        ),
        readiness_probe=_probe(
            _optional_object(data.get("readinessProbe"), "readinessProbe")
        ),
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
    persistent_volume_claim = _optional_object(
        data.get("persistentVolumeClaim"),
        "persistentVolumeClaim",
    )
    if persistent_volume_claim is not None:
        return PersistentVolumeClaimVolume(
            name=str(data["name"]),
            claim_name=str(persistent_volume_claim["claimName"]),
        )
    empty_dir = _optional_object(data.get("emptyDir"), "emptyDir")
    if empty_dir is not None:
        return EmptyDirVolume(
            name=str(data["name"]),
            medium=_optional_string(empty_dir.get("medium"), "emptyDir.medium"),
            size_limit=_optional_quantity(
                empty_dir.get("sizeLimit"),
                "emptyDir.sizeLimit",
            ),
        )
    config_map = _optional_object(data.get("configMap"), "configMap")
    if config_map is not None:
        return ConfigMapVolume(
            name=str(data["name"]),
            config_map_name=str(config_map["name"]),
            items=_key_to_paths(config_map.get("items")),
            default_mode=_optional_int(config_map.get("defaultMode"), "defaultMode"),
        )
    secret = _optional_object(data.get("secret"), "secret")
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
                value=_optional_string(item.get("value"), "dns option value"),
            )
            for item in data.get("options", [])
        ),
    )


def _container_security_context(data: JsonObject) -> ContainerSecurityContext:
    capabilities = _required_object(data.get("capabilities") or {}, "capabilities")
    return ContainerSecurityContext(
        privileged=bool(data.get("privileged", False)),
        allow_privilege_escalation=bool(data.get("allowPrivilegeEscalation", False)),
        read_only_root_filesystem=bool(data.get("readOnlyRootFilesystem", False)),
        run_as_non_root=bool(data.get("runAsNonRoot", False)),
        run_as_user=int(data.get("runAsUser") or 0),
        run_as_group=int(data.get("runAsGroup") or 0),
        capabilities_add=tuple(str(item) for item in capabilities.get("add", [])),
        capabilities_drop=tuple(str(item) for item in capabilities.get("drop", [])),
        proc_mount=_optional_string(data.get("procMount"), "procMount"),
        seccomp_profile=_seccomp_profile(
            _optional_object(data.get("seccompProfile"), "seccompProfile")
        ),
    )


def _seccomp_profile(data: JsonObject | None) -> SeccompProfile | None:
    if data is None:
        return None
    return SeccompProfile(
        profile_type=str(data["type"]),
        localhost_profile=_optional_string(
            data.get("localhostProfile"), "localhostProfile"
        ),
    )


def _probe(data: JsonObject | None) -> Probe | None:
    if data is None:
        return None
    exec_action = _optional_object(data.get("exec"), "exec")
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
        key=_optional_string(data.get("key"), "key"),
        operator=_optional_string(data.get("operator"), "operator"),
        value=_optional_string(data.get("value"), "value"),
        effect=_optional_string(data.get("effect"), "effect"),
        toleration_seconds=_optional_int(
            data.get("tolerationSeconds"), "tolerationSeconds"
        ),
    )


def _pod_status(status: JsonObject) -> PodStatus:
    conditions = status.get("conditions") or []
    ready_condition = next(
        (
            item
            for item in _object_list(conditions, "conditions")
            if item.get("type") == "Ready"
        ),
        None,
    )
    ready = ready_condition is not None and ready_condition.get("status") == "True"
    waiting_reason = _first_waiting_reason(
        _object_list(status.get("containerStatuses") or [], "containerStatuses")
    )
    termination_evidence = _first_termination_evidence(
        _object_list(status.get("containerStatuses") or [], "containerStatuses")
    )
    return PodStatus(
        phase=_optional_string(status.get("phase"), "phase"),
        ready=ready,
        ready_reason=(
            None
            if ready_condition is None
            else _optional_string(ready_condition.get("reason"), "ready reason")
        ),
        waiting_reason=waiting_reason,
        termination_evidence=termination_evidence,
    )


def _first_waiting_reason(container_statuses: list[JsonObject]) -> str | None:
    for item in container_statuses:
        state = _required_object(item.get("state") or {}, "container state")
        waiting = _optional_object(state.get("waiting"), "waiting state")
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
        state = _required_object(item.get("state") or {}, "container state")
        terminated = _optional_object(state.get("terminated"), "terminated state")
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
    spec = _required_object(data["spec"], "spec")
    resources = _required_object(spec.get("resources") or {}, "resources")
    requests = _required_object(resources.get("requests") or {}, "resource requests")
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
    spec = _required_object(data["spec"], "spec")
    cluster_ip = spec.get("clusterIP")
    if cluster_ip is not None and not isinstance(cluster_ip, str):
        raise RuntimeError("Service clusterIP must be a string")
    return ServiceResource(
        metadata=_object_meta(data),
        spec=ServiceSpec(
            service_type=str(spec.get("type") or "ClusterIP"),
            cluster_ip=cluster_ip,
            selector=_string_mapping(spec.get("selector") or {}, "selector"),
            ports=tuple(
                ServicePort(
                    name=_optional_string(item.get("name"), "port name"),
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
        data=_string_mapping(data.get("data") or {}, "data"),
        immutable=_optional_bool(data.get("immutable"), "ConfigMap immutable"),
    )


def secret_resource(data: JsonObject) -> SecretResource:
    """Parse one Provider-owned Secret into opaque byte values."""
    encoded = _required_object(data.get("data") or {}, "data")
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
    spec = _required_object(data["spec"], "spec")
    return NetworkPolicyResource(
        metadata=_object_meta(data),
        spec=NetworkPolicySpec(
            pod_selector=_label_selector_resource(
                _required_object(spec.get("podSelector") or {}, "podSelector")
            ),
            policy_types=tuple(str(item) for item in spec.get("policyTypes", [])),
            ingress=tuple(
                _network_policy_ingress_rule(_required_object(item, "array item"))
                for item in spec.get("ingress", [])
            ),
            egress=tuple(
                _network_policy_egress_rule(_required_object(item, "array item"))
                for item in spec.get("egress", [])
            ),
        ),
    )


def _network_policy_egress_rule(data: JsonObject) -> NetworkPolicyEgressRule:
    return NetworkPolicyEgressRule(
        peers=tuple(
            _network_policy_peer(_required_object(item, "array item"))
            for item in data.get("to", [])
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
            _network_policy_peer(_required_object(item, "array item"))
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
    ip_block = _optional_object(data.get("ipBlock"), "ipBlock")
    return NetworkPolicyPeer(
        namespace_selector=(
            None
            if data.get("namespaceSelector") is None
            else _label_selector_resource(
                _required_object(data["namespaceSelector"], "namespaceSelector")
            )
        ),
        pod_selector=(
            None
            if data.get("podSelector") is None
            else _label_selector_resource(
                _required_object(data["podSelector"], "podSelector")
            )
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
        match_labels=_string_mapping(
            data.get("matchLabels") or {},
            "matchLabels",
        ),
        match_expressions=tuple(
            _label_selector_requirement(_required_object(item, "array item"))
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
    spec = _required_object(data["spec"], "spec")
    metadata = _required_object(data.get("metadata") or {}, "metadata")
    return LeaseResource(
        metadata=_object_meta(data),
        spec=LeaseSpec(
            holder_identity=_optional_string(
                spec.get("holderIdentity"), "holderIdentity"
            ),
            acquire_time=_parse_datetime(
                _optional_string(spec.get("acquireTime"), "acquireTime")
            ),
            renew_time=_parse_datetime(
                _optional_string(spec.get("renewTime"), "renewTime")
            ),
            lease_duration_seconds=int(spec.get("leaseDurationSeconds") or 0),
            lease_transitions=int(spec.get("leaseTransitions") or 0),
        ),
        resource_version=_optional_string(
            metadata.get("resourceVersion"), "resourceVersion"
        ),
    )


def _object_meta(data: JsonObject) -> ObjectMeta:
    metadata = _required_object(data["metadata"], "metadata")
    return ObjectMeta(
        name=str(metadata["name"]),
        namespace=str(metadata["namespace"]),
        labels=_string_mapping(metadata.get("labels") or {}, "metadata.labels"),
        annotations=_string_mapping(
            metadata.get("annotations") or {}, "metadata.annotations"
        ),
        deletion_timestamp=_parse_datetime(
            _optional_string(metadata.get("deletionTimestamp"), "deletionTimestamp")
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
