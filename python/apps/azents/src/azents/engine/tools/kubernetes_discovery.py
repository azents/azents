"""Kubernetes API Resource Discovery.

Because lightkube create_namespaced_resource() requires plural name,
collect and cache kind->plural mapping from K8s API discovery endpoints.
"""

import dataclasses
import logging

from kubernetes_asyncio.client import (
    ApiClient,
    ApisApi,
    CoreV1Api,
    V1APIGroupList,
    V1APIResourceList,
)
from kubernetes_asyncio.client.exceptions import ApiException
from lightkube.generic_resource import (
    GenericGlobalResource,
    GenericNamespacedResource,
    create_global_resource,
    create_namespaced_resource,
    get_generic_resource,
)

from azents.utils.logging import sanitized_exception_info

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class ResourceInfo:
    """Resource metadata collected from API discovery."""

    group: str
    version: str
    kind: str
    plural: str
    namespaced: bool


class ResourceDiscoveryCache:
    """Cache API resource discovery results by cluster.

    Because lightkube create_namespaced_resource() requires plural name,
    Collect kind->plural mapping from /api/v1 + /apis/{group}/{version}.
    """

    def __init__(self) -> None:
        self._resources: dict[str, ResourceInfo] = {}
        self._resource_classes: dict[
            str, type[GenericNamespacedResource] | type[GenericGlobalResource]
        ] = {}

    async def discover(self, api_client: ApiClient) -> None:
        """Perform K8s API discovery and cache resource information.

        :param api_client: already-owned SDK client with cluster auth/proxy configured
        """
        await self._discover_core(api_client)
        await self._discover_apis(api_client)
        logger.info(
            "Completed API resource discovery",
            extra={"resource_count": len(self._resources)},
        )

    async def _discover_core(self, client: ApiClient) -> None:
        """Collect Core API (v1) resources."""
        response = await CoreV1Api(client).get_api_resources()
        if not isinstance(response, V1APIResourceList):
            raise TypeError("Core discovery did not return an SDK resource list.")
        self._collect_resources(response, group="", version="v1")

    async def _discover_apis(self, client: ApiClient) -> None:
        """Collect Named API groups resources."""
        response = await ApisApi(client).get_api_versions()
        if not isinstance(response, V1APIGroupList):
            raise TypeError("Group discovery did not return an SDK group list.")
        for group_info in response.groups or []:
            preferred_info = group_info.preferred_version
            if preferred_info is None or not preferred_info.version:
                continue
            group_name = group_info.name
            preferred = preferred_info.version
            try:
                # Installed custom groups have no generated operation; the
                # public client still owns auth, HTTP and typed deserialization.
                resources = await client.call_api(
                    f"/apis/{group_name}/{preferred}",
                    "GET",
                    header_params={"Accept": "application/json"},
                    response_types_map={200: "V1APIResourceList"},
                    auth_settings=["BearerToken"],
                    _return_http_data_only=True,
                )
                if not isinstance(resources, V1APIResourceList):
                    raise TypeError(
                        "Group discovery did not return an SDK resource list."
                    )
                self._collect_resources(resources, group=group_name, version=preferred)
            except ApiException as error:
                if not error.status:
                    raise
                logger.warning(
                    "Failed to discover API resources for group version",
                    extra={"group": group_name, "version": preferred},
                    exc_info=sanitized_exception_info(
                        error, message="Kubernetes group discovery failed"
                    ),
                )

    def _collect_resources(
        self, response: V1APIResourceList, *, group: str, version: str
    ) -> None:
        """Materialize typed resources, omitting subresource endpoints."""
        api_version = f"{group}/{version}" if group else version
        for resource in response.resources or []:
            if "/" in resource.name:
                continue
            self._resources[f"{api_version}/{resource.kind}"] = ResourceInfo(
                group=group,
                version=version,
                kind=resource.kind,
                plural=resource.name,
                namespaced=resource.namespaced,
            )

    def get_resource_class(
        self,
        api_version: str,
        kind: str,
    ) -> type[GenericNamespacedResource] | type[GenericGlobalResource]:
        """Return lightkube resource class by api_version + kind.

        :param api_version: API version, e.g. "v1", "apps/v1"
        :param kind: Resource kind, e.g. "Pod", "Deployment"
        :return: lightkube Generic resource class
        :raises KeyError: When resource was not collected by discover()
        """
        key = f"{api_version}/{kind}"
        cached = self._resource_classes.get(key)
        if cached is not None:
            return cached

        info = self._resources.get(key)
        if info is None:
            msg = f"Resource not found: {key}. Run discover() first."
            raise KeyError(msg)

        if "/" in api_version:
            group, version = api_version.split("/", 1)
        else:
            group, version = "", api_version

        # Reuse class already registered in lightkube global registry
        existing = get_generic_resource(api_version, kind)
        if existing is not None:
            cls: type[GenericNamespacedResource] | type[GenericGlobalResource] = (
                existing
            )
        elif info.namespaced:
            cls = create_namespaced_resource(group, version, kind, info.plural)
        else:
            cls = create_global_resource(group, version, kind, info.plural)

        self._resource_classes[key] = cls
        return cls

    def list_all(self) -> list[ResourceInfo]:
        """Return all cached resource list."""
        return sorted(
            self._resources.values(),
            key=lambda r: f"{r.group}/{r.version}/{r.kind}",
        )
