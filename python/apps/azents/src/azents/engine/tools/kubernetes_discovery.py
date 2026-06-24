"""Kubernetes API Resource Discovery.

Because lightkube create_namespaced_resource() requires plural name,
collect and cache kind->plural mapping from K8s API discovery endpoints.
"""

import dataclasses
import logging

import httpx
from lightkube.generic_resource import (
    GenericGlobalResource,
    GenericNamespacedResource,
    create_global_resource,
    create_namespaced_resource,
    get_generic_resource,
)

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

    async def discover(self, httpx_client: httpx.AsyncClient) -> None:
        """Perform K8s API discovery and cache resource information.

        :param httpx_client: httpx client with authentication configured
        """
        await self._discover_core(httpx_client)
        await self._discover_apis(httpx_client)
        logger.info(
            "Completed API resource discovery",
            extra={"resource_count": len(self._resources)},
        )

    async def _discover_core(self, client: httpx.AsyncClient) -> None:
        """Collect Core API (v1) resources."""
        resp = await client.get("/api/v1")
        resp.raise_for_status()
        data = resp.json()
        for r in data.get("resources", []):
            if "/" in r["name"]:
                continue
            info = ResourceInfo(
                group="",
                version="v1",
                kind=r["kind"],
                plural=r["name"],
                namespaced=r["namespaced"],
            )
            self._resources[f"v1/{r['kind']}"] = info

    async def _discover_apis(self, client: httpx.AsyncClient) -> None:
        """Collect Named API groups resources."""
        resp = await client.get("/apis")
        resp.raise_for_status()
        groups_data = resp.json()
        for group_info in groups_data.get("groups", []):
            group_name: str = group_info["name"]
            preferred: str | None = group_info.get("preferredVersion", {}).get(
                "version"
            )
            if not preferred:
                continue
            api_version = f"{group_name}/{preferred}"
            try:
                ver_resp = await client.get(f"/apis/{group_name}/{preferred}")
                ver_resp.raise_for_status()
                ver_data = ver_resp.json()
                for r in ver_data.get("resources", []):
                    if "/" in r["name"]:
                        continue
                    info = ResourceInfo(
                        group=group_name,
                        version=preferred,
                        kind=r["kind"],
                        plural=r["name"],
                        namespaced=r["namespaced"],
                    )
                    self._resources[f"{api_version}/{r['kind']}"] = info
            except httpx.HTTPStatusError:
                logger.warning(
                    "Failed to discover API resources for group version",
                    extra={"group": group_name, "version": preferred},
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
