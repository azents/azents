"""ResourceDiscoveryCache tests."""

import dataclasses
import json
from collections.abc import AsyncGenerator
from typing import NamedTuple
from unittest.mock import AsyncMock, create_autospec, patch
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from aiohttp import ClientResponse
from kubernetes_asyncio.client import (
    ApiClient,
    Configuration,
    V1APIGroup,
    V1APIGroupList,
    V1GroupVersionForDiscovery,
    rest,
)
from kubernetes_asyncio.client.exceptions import ApiException
from lightkube.generic_resource import GenericGlobalResource, GenericNamespacedResource
from multidict import CIMultiDict, CIMultiDictProxy

from azents.engine.tools.kubernetes_discovery import (
    ResourceDiscoveryCache,
    ResourceInfo,
)


def _make_mock_response(data: dict[str, object]) -> rest.RESTResponse:
    """Create a native wire receipt for the actual SDK deserializer."""
    resources = data.get("resources")
    if isinstance(resources, list):
        for resource in resources:
            assert isinstance(resource, dict)
            kind = resource["kind"]
            assert isinstance(kind, str)
            resource["singularName"] = kind.lower()
            resource["verbs"] = ["get", "list"]
    groups = data.get("groups")
    if isinstance(groups, list):
        for group in groups:
            assert isinstance(group, dict)
            preferred = group["preferredVersion"]
            assert isinstance(preferred, dict)
            preferred["groupVersion"] = f"{group['name']}/{preferred['version']}"
            group["versions"] = [preferred]
    head = create_autospec(ClientResponse, instance=True)
    head.status = 200
    head.reason = "OK"
    head.headers = CIMultiDictProxy(CIMultiDict({"Content-Type": "application/json"}))
    return rest.RESTResponse(head, json.dumps(data).encode())


def _make_core_v1_response() -> rest.RESTResponse:
    """Create Core v1 API response."""
    return _make_mock_response(
        {
            "groupVersion": "v1",
            "resources": [
                {"name": "pods", "kind": "Pod", "namespaced": True},
                {"name": "namespaces", "kind": "Namespace", "namespaced": False},
                {"name": "services", "kind": "Service", "namespaced": True},
                # Subresource: should be ignored
                {"name": "pods/log", "kind": "Pod", "namespaced": True},
                {"name": "pods/status", "kind": "Pod", "namespaced": True},
            ],
        }
    )


def _make_apis_response() -> rest.RESTResponse:
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


def _make_apps_v1_response() -> rest.RESTResponse:
    """Create apps/v1 API response."""
    return _make_mock_response(
        {
            "groupVersion": "apps/v1",
            "resources": [
                {"name": "deployments", "kind": "Deployment", "namespaced": True},
                {"name": "daemonsets", "kind": "DaemonSet", "namespaced": True},
                # Subresource
                {
                    "name": "deployments/scale",
                    "kind": "Scale",
                    "namespaced": True,
                },
            ],
        }
    )


def _make_batch_v1_response() -> rest.RESTResponse:
    """Create batch/v1 API response."""
    return _make_mock_response(
        {
            "groupVersion": "batch/v1",
            "resources": [
                {"name": "jobs", "kind": "Job", "namespaced": True},
                {"name": "cronjobs", "kind": "CronJob", "namespaced": True},
            ],
        }
    )


class TestResourceDiscoveryCache:
    """ResourceDiscoveryCache tests."""

    @pytest_asyncio.fixture
    async def mock_client(self) -> AsyncGenerator[ApiClient, None]:
        """Exercise actual SDK authentication and response model decoding."""
        configuration = Configuration(host="https://cluster.example.test")
        configuration.api_key["BearerToken"] = "Bearer local-token"

        def _get(url: str, **_: object) -> rest.RESTResponse:
            responses: dict[str, rest.RESTResponse] = {
                "/api/v1/": _make_core_v1_response(),
                "/apis/": _make_apis_response(),
                "/apis/apps/v1": _make_apps_v1_response(),
                "/apis/batch/v1": _make_batch_v1_response(),
            }
            return responses[urlsplit(url).path]

        async with ApiClient(configuration=configuration) as client:
            with patch.object(client.rest_client, "GET", AsyncMock(side_effect=_get)):
                yield client

    @pytest.mark.asyncio
    async def test_discover(self, mock_client: ApiClient) -> None:
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
    async def test_public_sdk_preserves_auth_and_preferred_group_paths(
        self, mock_client: ApiClient
    ) -> None:
        """Auth and typed decoding run through the existing owned SDK client."""

        class RequestEvidence(NamedTuple):
            path: str
            authorization: str

        calls: list[RequestEvidence] = []

        def get(url: str, *, headers: dict[str, str], **_: object) -> rest.RESTResponse:
            path = urlsplit(url).path
            calls.append(
                RequestEvidence(path=path, authorization=headers["authorization"])
            )
            replies = {
                "/api/v1/": _make_core_v1_response(),
                "/apis/": _make_apis_response(),
                "/apis/apps/v1": _make_apps_v1_response(),
                "/apis/batch/v1": _make_batch_v1_response(),
            }
            return replies[path]

        cache = ResourceDiscoveryCache()
        with patch.object(mock_client.rest_client, "GET", AsyncMock(side_effect=get)):
            await cache.discover(mock_client)
        assert [call.path for call in calls] == [
            "/api/v1/",
            "/apis/",
            "/apis/apps/v1",
            "/apis/batch/v1",
        ]
        assert all(call.authorization == "Bearer local-token" for call in calls)
        assert cache.get_resource_class("apps/v1", "Deployment")

    @pytest.mark.asyncio
    async def test_group_without_preferred_version_is_not_dispatched(
        self, mock_client: ApiClient
    ) -> None:
        """A typed optional preferred version preserves the existing skip behavior."""
        group_list = V1APIGroupList(
            groups=[
                V1APIGroup(
                    name="unselected",
                    versions=[
                        V1GroupVersionForDiscovery(
                            group_version="unselected/v1", version="v1"
                        )
                    ],
                )
            ]
        )
        seen: list[str] = []

        def get(url: str, **_: object) -> rest.RESTResponse:
            path = urlsplit(url).path
            seen.append(path)
            if path == "/api/v1/":
                return _make_core_v1_response()
            assert path == "/apis/"
            head = create_autospec(ClientResponse, instance=True)
            head.status = 200
            head.reason = "OK"
            head.headers = CIMultiDictProxy(
                CIMultiDict({"Content-Type": "application/json"})
            )
            return rest.RESTResponse(
                head,
                json.dumps(mock_client.sanitize_for_serialization(group_list)).encode(),
            )

        cache = ResourceDiscoveryCache()
        with patch.object(mock_client.rest_client, "GET", AsyncMock(side_effect=get)):
            await cache.discover(mock_client)
        assert seen == ["/api/v1/", "/apis/"]
        assert len(cache.list_all()) == 3

    @pytest.mark.asyncio
    async def test_discover_apis_error_skipped(self, mock_client: ApiClient) -> None:
        """Skip only corresponding group when API group discovery fails."""

        def _get(url: str, **_: object) -> rest.RESTResponse:
            path = urlsplit(url).path
            if path == "/api/v1/":
                return _make_core_v1_response()
            if path == "/apis/":
                return _make_apis_response()
            if path == "/apis/apps/v1":
                error = ApiException(status=503, reason="Service Unavailable")
                error.body = b"Service Unavailable"
                raise error
            if path == "/apis/batch/v1":
                return _make_batch_v1_response()
            msg = f"Unexpected URL: {url}"
            raise ValueError(msg)

        cache = ResourceDiscoveryCache()
        with patch.object(mock_client.rest_client, "GET", AsyncMock(side_effect=_get)):
            await cache.discover(mock_client)

        resources = cache.list_all()
        kinds = {r.kind for r in resources}
        # apps group failed, so core + batch only
        assert "Deployment" not in kinds
        assert "Pod" in kinds
        assert "Job" in kinds

    @pytest.mark.asyncio
    async def test_get_resource_class_namespaced(self, mock_client: ApiClient) -> None:
        """Namespaced resource class is created correctly."""
        cache = ResourceDiscoveryCache()
        await cache.discover(mock_client)

        cls = cache.get_resource_class("v1", "Pod")
        assert issubclass(cls, GenericNamespacedResource)

    @pytest.mark.asyncio
    async def test_get_resource_class_global(self, mock_client: ApiClient) -> None:
        """Global resource class is created correctly."""
        cache = ResourceDiscoveryCache()
        await cache.discover(mock_client)

        cls = cache.get_resource_class("v1", "Namespace")
        assert issubclass(cls, GenericGlobalResource)

    @pytest.mark.asyncio
    async def test_get_resource_class_with_group(self, mock_client: ApiClient) -> None:
        """Resource class with group is created correctly."""
        cache = ResourceDiscoveryCache()
        await cache.discover(mock_client)

        cls = cache.get_resource_class("apps/v1", "Deployment")
        assert issubclass(cls, GenericNamespacedResource)

    @pytest.mark.asyncio
    async def test_get_resource_class_cached(self, mock_client: ApiClient) -> None:
        """Resource class is cached."""
        cache = ResourceDiscoveryCache()
        await cache.discover(mock_client)

        cls1 = cache.get_resource_class("v1", "Pod")
        cls2 = cache.get_resource_class("v1", "Pod")
        assert cls1 is cls2

    @pytest.mark.asyncio
    async def test_get_resource_class_not_found(self, mock_client: ApiClient) -> None:
        """KeyError when requesting uncollected resource."""
        cache = ResourceDiscoveryCache()
        await cache.discover(mock_client)

        with pytest.raises(KeyError, match="Resource not found"):
            cache.get_resource_class("v1", "Unknown")

    @pytest.mark.asyncio
    async def test_list_all_sorted(self, mock_client: ApiClient) -> None:
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
        with pytest.raises(dataclasses.FrozenInstanceError):
            ResourceInfo.__setattr__(info, "kind", "Service")
