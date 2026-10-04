"""Expected and unexpected discovery faults at concrete Toolkit boundaries."""

import asyncio
import logging
from typing import Literal, assert_never
from unittest.mock import AsyncMock, create_autospec, patch

import httpx2
import pytest
from google.api_core.exceptions import PermissionDenied
from kubernetes_asyncio.client import ApiClient
from kubernetes_asyncio.client.exceptions import ApiException
from lightkube import AsyncClient

from azents.core.github_credentials import GitHubInstallationTarget
from azents.core.tools import (
    ClusterConfig,
    GitHubToolkitConfig,
    KubernetesToolkitConfig,
    McpToolkitConfig,
)
from azents.engine.run.types import FunctionToolError
from azents.engine.tools.aws_test import _make_toolkit as _aws_toolkit
from azents.engine.tools.background_discovery import (
    observe_discovery_failure,
    require_expected_discovery_failure,
)
from azents.engine.tools.gcp_test import (
    _FakeToolkitStateHandle,
    _FakeToolkitStateStore,
)
from azents.engine.tools.gcp_test import (
    _make_toolkit as _gcp_toolkit,
)
from azents.engine.tools.github import GitHubToolkit
from azents.engine.tools.github_tool_snapshot_test import _binding
from azents.engine.tools.kubernetes import KubernetesToolkit, KubernetesToolkitProvider
from azents.engine.tools.kubernetes_auth import KubernetesCredentials, TokenCredential
from azents.engine.tools.kubernetes_discovery import ResourceDiscoveryCache
from azents.engine.tools.kubernetes_test import _make_resolve_context


@pytest.fixture(autouse=True)
def _snapshot_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep snapshot ownership cases deterministic without a database."""
    _FakeToolkitStateHandle.clear()
    monkeypatch.setattr(
        "azents.repos.toolkit_state.engine.ToolkitStateStore", _FakeToolkitStateStore
    )


@pytest.mark.parametrize("kind", ["aws", "gcp"])
@pytest.mark.parametrize("failure", ["network", "unexpected", "mixed", "cancel"])
async def test_concrete_refresh_error_classification(
    kind: Literal["aws", "gcp"],
    failure: Literal["network", "unexpected", "mixed", "cancel"],
) -> None:
    """Remote failure stays nonfatal; bugs, mixed groups and cancellation propagate."""
    toolkit = _aws_toolkit() if kind == "aws" else _gcp_toolkit()
    remote = httpx2.ConnectError("Remote unavailable")
    error: BaseException
    match failure:
        case "network":
            error = remote
        case "unexpected":
            error = ValueError("Unexpected projection invariant")
        case "mixed":
            error = ExceptionGroup("Mixed discovery", [remote, TypeError("bug")])
        case "cancel":
            error = asyncio.CancelledError()
        case _ as unreachable:
            assert_never(unreachable)
    with patch(
        f"azents.engine.tools.{kind}.mcp_list_tools", AsyncMock(side_effect=error)
    ):
        if failure == "network":
            await toolkit._refresh_tool_snapshot()
        else:
            with pytest.raises(type(error)) as caught:
                await toolkit._refresh_tool_snapshot()
            assert caught.value is error


@pytest.mark.parametrize("kind", ["aws", "gcp"])
async def test_unexpected_background_fault_is_observed_once(
    kind: Literal["aws", "gcp"], caplog: pytest.LogCaptureFixture
) -> None:
    """Synchronize error observation with the explicit task-done boundary."""
    toolkit = _aws_toolkit() if kind == "aws" else _gcp_toolkit()
    error = TypeError("secret-marker-not-for-logs")
    observed = asyncio.Event()
    with patch(
        f"azents.engine.tools.{kind}.mcp_list_tools", AsyncMock(side_effect=error)
    ):
        await toolkit.__aenter__()
        task = toolkit._bg_task
        assert task is not None
        task.add_done_callback(lambda _: observed.set())
        with pytest.raises(TypeError) as caught:
            await task
        assert caught.value is error
        await observed.wait()
        await toolkit.__aexit__()
    records = [
        record
        for record in caplog.records
        if record.message == "Unexpected Toolkit discovery failure"
    ]
    assert len(records) == 1
    assert "secret-marker-not-for-logs" not in caplog.text


@pytest.mark.parametrize("binding_mode", [False, True])
@pytest.mark.parametrize("expected", [False, True])
async def test_github_lazy_credential_boundary(
    binding_mode: bool, expected: bool
) -> None:
    """Both lazy paths distinguish known transport failure from an arbitrary bug."""
    error = httpx2.ConnectError("Remote unavailable") if expected else ValueError("bug")

    async def token() -> str | None:
        raise error

    toolkit = GitHubToolkit(
        config=GitHubToolkitConfig(github_auth_type="pat"),
        lazy_mcp_config=McpToolkitConfig(
            server_url="https://example.test/mcp", auth_type="bearer"
        ),
        lazy_mcp_secret_provider=token,
    )
    binding = _binding(
        target=GitHubInstallationTarget(
            installation_id="1",
            account_login="test",
            account_type="User",
            account_avatar_url=None,
        ),
        state_name="test",
        token_provider=token,
    )
    if expected:
        if binding_mode:
            await toolkit._prepare_installation_mcp(binding)
            assert binding.lazy_mcp_error is not None
        else:
            await toolkit._prepare_lazy_mcp()
            assert toolkit._lazy_mcp_error is not None
    else:
        with pytest.raises(ValueError) as caught:
            if binding_mode:
                await toolkit._prepare_installation_mcp(binding)
            else:
                await toolkit._prepare_lazy_mcp()
        assert caught.value is error
        assert binding.lazy_mcp_error is None
        assert toolkit._lazy_mcp_error is None


def test_expected_group_classifier_preserves_unrelated_siblings() -> None:
    """A handled network leaf cannot suppress a sibling invariant error."""
    require_expected_discovery_failure(
        ExceptionGroup("Remote", [httpx2.ConnectError("Remote")])
    )
    mixed = ExceptionGroup("Mixed", [httpx2.ConnectError("Remote"), ValueError("bug")])
    with pytest.raises(ExceptionGroup) as caught:
        require_expected_discovery_failure(mixed)
    assert caught.value is mixed


async def test_cancelled_observer_does_not_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The task observer retains cancellation without producing failure logs."""
    gate = asyncio.Event()

    async def wait() -> None:
        await gate.wait()

    discovery = asyncio.create_task(wait())
    discovery.cancel()
    with pytest.raises(asyncio.CancelledError):
        await discovery
    observe_discovery_failure(logging.getLogger(__name__), toolkit="test")(discovery)
    assert caplog.records == []


@pytest.mark.parametrize("failure", ["api", "google", "unexpected", "cancel"])
async def test_kubernetes_initialization_closes_partial_clients(
    failure: Literal["api", "google", "unexpected", "cancel"],
) -> None:
    """Expected errors translate; bugs/cancellation keep identity after both closes."""
    resource_client = create_autospec(AsyncClient, instance=True)
    exec_client = create_autospec(ApiClient, instance=True)
    cache = create_autospec(ResourceDiscoveryCache, instance=True)
    error: BaseException
    match failure:
        case "api":
            error = ApiException(status=403, reason="Forbidden")
        case "google":
            error = PermissionDenied("Denied")
        case "unexpected":
            error = ValueError("Discovery invariant")
        case "cancel":
            error = asyncio.CancelledError()
        case _ as unreachable:
            assert_never(unreachable)
    cache.discover.side_effect = error
    credentials = KubernetesCredentials(
        clusters={"staging": TokenCredential(token="local-token")}
    ).model_dump_json()
    with (
        patch(
            "azents.engine.tools.kubernetes.create_lightkube_client",
            AsyncMock(return_value=resource_client),
        ),
        patch(
            "azents.engine.tools.kubernetes.create_exec_api_client",
            AsyncMock(return_value=exec_client),
        ),
        patch(
            "azents.engine.tools.kubernetes.ResourceDiscoveryCache",
            return_value=cache,
        ),
    ):
        toolkit = await KubernetesToolkitProvider().resolve(
            KubernetesToolkitConfig(
                clusters=[ClusterConfig(name="staging", auth_type="token")]
            ),
            _make_resolve_context(credentials),
        )
        assert isinstance(toolkit, KubernetesToolkit)
        if failure in {"api", "google"}:
            with pytest.raises(FunctionToolError):
                await toolkit._ensure_cluster_clients("staging")
        else:
            with pytest.raises(type(error)) as caught:
                await toolkit._ensure_cluster_clients("staging")
            assert caught.value is error
    cache.discover.assert_awaited_once_with(exec_client)
    resource_client.close.assert_awaited_once()
    exec_client.close.assert_awaited_once()
    assert toolkit._clients == {}
    assert toolkit._exec_clients == {}
