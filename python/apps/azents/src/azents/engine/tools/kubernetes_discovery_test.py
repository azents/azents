"""ResourceDiscoveryCache tests."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest
from lightkube.generic_resource import GenericGlobalResource, GenericNamespacedResource

from azents.engine.tools.kubernetes_discovery import (
    ResourceDiscoveryCache,
    ResourceInfo,
)


def _make_mock_response(data: dict[str, object]) -> httpx.Response:
    """Create httpx.Response for tests."""
    return httpx.Response(
        status_code=200,
        content=json.dumps(data).encode(),
        request=httpx.Request("GET", "http://test"),
    )


def _make_core_v1_response() -> httpx.Response:
    """Create Core v1 API response."""
    return _make_mock_response(
        {
            "resources": [
                {"name": "pods", "kind": "Pod", "namespaced": True},
                {"name": "namespaces", "kind": "Namespace", "namespaced": False},
                {"name": "services", "kind": "Service", "namespaced": True},
                # Subresource: should be ignored
                {"name": "pods/log", "kind": "Pod", "namespaced": True},
                {"name": "pods/status", "kind": "Pod", "namespaced": True},
            ]
        }
    )


def _make_apis_response() -> httpx.Response:
    """Create API groups response."""
    return _make_mock_response(
        {
            "groups": [
                {
                    "name": "apps",
                    "preferredVersion": {"version": "v1"},
                },
                {
                    "name": "batch",
                    "preferredVersion": {"version": "v1"},
                },
            ]
        }
    )


def _make_apps_v1_response() -> httpx.Response:
    """Create apps/v1 API response."""
    return _make_mock_response(
        {
            "resources": [
                {"name": "deployments", "kind": "Deployment", "namespaced": True},
                {"name": "daemonsets", "kind": "DaemonSet", "namespaced": True},
                # Subresource
                {
                    "name": "deployments/scale",
                    "kind": "Scale",
                    "namespaced": True,
                },
            ]
        }
    )


def _make_batch_v1_response() -> httpx.Response:
    """Create batch/v1 API response."""
    return _make_mock_response(
        {
            "resources": [
                {"name": "jobs", "kind": "Job", "namespaced": True},
                {"name": "cronjobs", "kind": "CronJob", "namespaced": True},
            ]
        }
    )


class TestResourceDiscoveryCache:
    """ResourceDiscoveryCache tests."""

    @pytest.fixture
    def mock_client(self) -> AsyncMock:
        """Create mock httpx client with authentication configured."""
        client = AsyncMock(spec=httpx.AsyncClient)

        def _get(url: str) -> httpx.Response:
            responses: dict[str, httpx.Response] = {
                "/api/v1": _make_core_v1_response(),
                "/apis": _make_apis_response(),
                "/apis/apps/v1": _make_apps_v1_response(),
                "/apis/batch/v1": _make_batch_v1_response(),
            }
            return responses[url]

        client.get = AsyncMock(side_effect=_get)
        return client

    @pytest.mark.asyncio
    async def test_discover(self, mock_client: AsyncMock) -> None:
        """Full discovery works normally."""
        cache = ResourceDiscoveryCache()
        await cache.discover(mock_client)

        resources = cache.list_all()
        kinds = {r.kind for r in resources}
        # Core v1 resources
        assert "Pod" in kinds
        assert "Namespace" in kinds
        assert "Service" in kinds
        # Named API groups resources
        assert "Deployment" in kinds
        assert "DaemonSet" in kinds
        assert "Job" in kinds
        assert "CronJob" in kinds
        # core(3) + apps(2) + batch(2) = 7, excluding subresources
        assert len(resources) == 7

    @pytest.mark.asyncio
    async def test_discover_apis_error_skipped(self, mock_client: AsyncMock) -> None:
        """Skip only corresponding group when API group discovery fails."""

        def _get(url: str) -> httpx.Response:
            if url == "/api/v1":
                return _make_core_v1_response()
            if url == "/apis":
                return _make_apis_response()
            if url == "/apis/apps/v1":
                return httpx.Response(
                    status_code=503,
                    content=b"Service Unavailable",
                    request=httpx.Request("GET", url),
                )
            if url == "/apis/batch/v1":
                return _make_batch_v1_response()
            msg = f"Unexpected URL: {url}"
            raise ValueError(msg)

        mock_client.get = AsyncMock(side_effect=_get)
        cache = ResourceDiscoveryCache()
        await cache.discover(mock_client)

        resources = cache.list_all()
        kinds = {r.kind for r in resources}
        # apps group failed, so core + batch only
        assert "Deployment" not in kinds
        assert "Pod" in kinds
        assert "Job" in kinds

    @pytest.mark.asyncio
    async def test_get_resource_class_namespaced(self, mock_client: AsyncMock) -> None:
        """Namespaced resource class is created correctly."""
        cache = ResourceDiscoveryCache()
        await cache.discover(mock_client)

        cls = cache.get_resource_class("v1", "Pod")
        assert issubclass(cls, GenericNamespacedResource)

    @pytest.mark.asyncio
    async def test_get_resource_class_global(self, mock_client: AsyncMock) -> None:
        """Global resource class is created correctly."""
        cache = ResourceDiscoveryCache()
        await cache.discover(mock_client)

        cls = cache.get_resource_class("v1", "Namespace")
        assert issubclass(cls, GenericGlobalResource)

    @pytest.mark.asyncio
    async def test_get_resource_class_with_group(self, mock_client: AsyncMock) -> None:
        """Resource class with group is created correctly."""
        cache = ResourceDiscoveryCache()
        await cache.discover(mock_client)

        cls = cache.get_resource_class("apps/v1", "Deployment")
        assert issubclass(cls, GenericNamespacedResource)

    @pytest.mark.asyncio
    async def test_get_resource_class_cached(self, mock_client: AsyncMock) -> None:
        """Resource class is cached."""
        cache = ResourceDiscoveryCache()
        await cache.discover(mock_client)

        cls1 = cache.get_resource_class("v1", "Pod")
        cls2 = cache.get_resource_class("v1", "Pod")
        assert cls1 is cls2

    @pytest.mark.asyncio
    async def test_get_resource_class_not_found(self, mock_client: AsyncMock) -> None:
        """KeyError when requesting uncollected resource."""
        cache = ResourceDiscoveryCache()
        await cache.discover(mock_client)

        with pytest.raises(KeyError, match="Resource not found"):
            cache.get_resource_class("v1", "Unknown")

    @pytest.mark.asyncio
    async def test_list_all_sorted(self, mock_client: AsyncMock) -> None:
        """list_all() returns sorted results."""
        cache = ResourceDiscoveryCache()
        await cache.discover(mock_client)

        resources = cache.list_all()
        keys = [f"{r.group}/{r.version}/{r.kind}" for r in resources]
        assert keys == sorted(keys)

    def test_resource_info_frozen(self) -> None:
        """ResourceInfo is frozen dataclass."""
        info = ResourceInfo(
            group="", version="v1", kind="Pod", plural="pods", namespaced=True
        )
        with pytest.raises(AttributeError):
            info.kind = "Service"  # type: ignore[misc]
