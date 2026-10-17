"""Native Kubernetes cached clients and lazy gaps retain personal authority."""

from unittest.mock import AsyncMock, Mock

import pytest

from azents.core.tools import ClusterConfig, KubernetesToolkitConfig
from azents.engine.run.types import FunctionToolError
from azents.engine.tooling.personal_admission import PersonalToolkitAdmission
from azents.engine.tools import kubernetes as k8s
from azents.engine.tools.kubernetes_auth import KubernetesCredentials, TokenCredential
from azents.engine.tools.personal_mcp_test import restrict
from azents.repos.toolkit.personal_runtime_test import Harness
from azents.repos.toolkit.personal_runtime_test import (
    fixture as fixture,  # noqa: PLC0414 -- committed PostgreSQL fixture
)
from azents.repos.toolkit.personal_runtime_test import (
    runtime as runtime,  # noqa: PLC0414 -- canonical root/current policy
)
from azents.repos.toolkit.personal_test import creation


@pytest.mark.parametrize("timing", ["before", "client_gap", "discovery_gap", "cached"])
async def test_native_kubernetes_rechecks_credentials_and_cached_client_authority(
    runtime: Harness,
    monkeypatch: pytest.MonkeyPatch,
    timing: str,
) -> None:
    h = runtime
    saved = await h.foundation.operations.create(
        user_id=h.foundation.user_id,
        create=creation().model_copy(update={"toolkit_type": "kubernetes"}),
    )
    root = await h.root(h.foundation.user_id, 0)
    [source] = await h.sources(root)
    toolkit = k8s.KubernetesToolkit(
        config=KubernetesToolkitConfig(
            clusters=[ClusterConfig(name="fixture", auth_type="token")]
        ),
        credentials=KubernetesCredentials(
            clusters={"fixture": TokenCredential(token="fixture-token")}
        ),
    )
    toolkit.bind_effect_admission(PersonalToolkitAdmission(h.repository, source.target))
    resource = AsyncMock(spec=k8s.AsyncClient)
    executor = AsyncMock(spec=k8s.ApiClient)
    cache = Mock(spec=k8s.ResourceDiscoveryCache)

    async def create_client(*args: object, **kwargs: object) -> k8s.AsyncClient:
        del args, kwargs
        if timing == "client_gap":
            await restrict(h, root, saved.id)
        return resource

    async def discover(*args: object, **kwargs: object) -> None:
        del args, kwargs
        if timing == "discovery_gap":
            await restrict(h, root, saved.id)

    create = AsyncMock(side_effect=create_client)
    create_exec = AsyncMock(return_value=executor)
    cache.discover = AsyncMock(side_effect=discover)
    monkeypatch.setattr(k8s, "create_lightkube_client", create)
    monkeypatch.setattr(k8s, "create_exec_api_client", create_exec)
    monkeypatch.setattr(k8s, "ResourceDiscoveryCache", Mock(return_value=cache))
    if timing == "cached":
        await toolkit._ensure_cluster_clients("fixture")
        await restrict(h, root, saved.id)
    elif timing == "before":
        await restrict(h, root, saved.id)
    with pytest.raises(FunctionToolError):
        await toolkit._ensure_cluster_clients("fixture")
    if timing == "before":
        create.assert_not_awaited()
        create_exec.assert_not_awaited()
    elif timing == "client_gap":
        create.assert_awaited_once()
        create_exec.assert_not_awaited()
        resource.close.assert_awaited_once()
        assert not toolkit._clients
    elif timing == "discovery_gap":
        resource.close.assert_awaited_once()
        executor.close.assert_awaited_once()
        assert not toolkit._clients
    else:
        create.assert_awaited_once()
        create_exec.assert_awaited_once()
        cache.discover.assert_awaited_once()
    await toolkit.__aexit__(None, None, None)
