"""One Control connection owns and joins every background task on exit."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from azents_runtime_provider_kubernetes import main
from azents_runtime_provider_kubernetes.deployment_diagnostics import (
    DeploymentDiagnosticSettings,
    OperationalDiagnosticsState,
)
from azents_runtime_provider_kubernetes.kubernetes_http import KubernetesHttpApi


@pytest.mark.parametrize("exit_mode", ["cancel", "failure", "complete"])
async def test_connection_joins_children_before_client_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, exit_mode: str
) -> None:
    """Cancellation, child errors, and normal completion drain the same owner."""
    settings = MagicMock(spec=main.ProviderSettings)
    settings.namespace = "provider"
    settings.workload_namespace = "runtime"
    settings.control_endpoint = "control:8030"
    settings.mandatory_services = ()
    settings.default_deny_labels = {}
    settings.attest_proxy_required = False
    settings.proxy_image = None
    settings.proxy_addon_digest = None
    settings.provider_id = "provider"
    settings.connection_id = "connection"
    settings.readiness_file = tmp_path / "ready"
    settings.service_account_token_file = tmp_path / "token"
    settings.diagnostic_refresh_interval_seconds = 30
    api = MagicMock(spec=KubernetesHttpApi)
    prepared = MagicMock(spec=main.PreparedRuntimeProvider)
    prepared.lifecycle = MagicMock()
    prepared.registration = MagicMock()
    monkeypatch.setattr(
        main, "prepare_runtime_provider", AsyncMock(return_value=prepared)
    )
    monkeypatch.setattr(
        main,
        "DeploymentDiagnosticSettings",
        MagicMock(spec=DeploymentDiagnosticSettings),
    )
    monkeypatch.setattr(
        main, "OperationalDiagnosticsState", MagicMock(spec=OperationalDiagnosticsState)
    )
    monkeypatch.setattr(main, "collect_operational_diagnostics", AsyncMock())
    monkeypatch.setattr(main, "read_service_account_token", lambda _path: "synthetic")
    started = [asyncio.Event() for _ in range(4)]
    stopped = [asyncio.Event() for _ in range(4)]
    release = asyncio.Event()
    stop = asyncio.Event()

    async def child(index: int) -> None:
        started[index].set()
        try:
            if index == 1:
                await release.wait()
                if exit_mode == "failure":
                    raise ValueError("command failed")
                stop.set()
                return
            await asyncio.Event().wait()
        finally:
            stopped[index].set()

    run_loop = MagicMock(spec=main.ProviderRunLoop)
    run_loop.start = AsyncMock()
    run_loop.run_forever = lambda **_kwargs: child(1)
    monkeypatch.setattr(main, "ProviderRunLoop", MagicMock(return_value=run_loop))
    monkeypatch.setattr(
        main, "_report_pod_watch_events", lambda *_args, **_kwargs: child(0)
    )
    monkeypatch.setattr(
        main, "wait_for_provider_credential_change", lambda *_args, **_kwargs: child(2)
    )
    monkeypatch.setattr(
        main, "refresh_operational_diagnostics", lambda *_args, **_kwargs: child(3)
    )

    async def close() -> None:
        assert all(event.is_set() for event in stopped)

    client = MagicMock()
    client.close = AsyncMock(side_effect=close)
    monkeypatch.setattr(
        main, "create_provider_control_client", MagicMock(return_value=client)
    )
    owner = asyncio.create_task(main._run_control_loop(settings, api, stop=stop))
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started)), 1)
        if exit_mode == "cancel":
            owner.cancel()
            with pytest.raises(asyncio.CancelledError):
                await owner
        elif exit_mode == "failure":
            release.set()
            with pytest.raises(ValueError, match="command failed"):
                await asyncio.wait_for(owner, 1)
        else:
            release.set()
            await asyncio.wait_for(owner, 1)
        client.close.assert_awaited_once_with()
        assert all(event.is_set() for event in stopped)
        assert not settings.readiness_file.exists()
    finally:
        if not owner.done():
            owner.cancel()
        await asyncio.gather(owner, return_exceptions=True)
