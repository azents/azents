"""Local all-in-one devserver composition tests."""

from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import MagicMock, create_autospec

import pytest
from azcommon import di
from fastapi import FastAPI

import cli.devserver as devserver
from azents.broker.deps import get_broker
from azents.broker.types import SessionWakeUp
from azents.core.config import Config, Settings
from azents.core.deps import AppContextBinding
from azents.core.enums import JobRuntimeBackend
from azents.process_lifecycle import create_container
from azents.runtime.control_server import RuntimeControlSettings
from azents.runtime.coordination.local import LocalRuntimeStores
from azents.runtime.deps import (
    get_runtime_coordination_store,
    get_runtime_terminal_coordination_store,
)
from azents.utils.appctx import AppContext
from azents.worker.deps import get_worker_broker
from cli.devserver import _create_api_targets, _run_devserver_resources


def test_non_reload_api_apps_share_root_appcontext_and_container() -> None:
    """Co-located API roles use the Worker/Scheduler process DI base."""
    config = Config.model_construct(job_runtime_backend=JobRuntimeBackend.LOCAL)
    appctx = AppContext(config)
    container = create_container(appctx)

    public, admin = _create_api_targets(
        config,
        appctx=appctx,
        container=container,
        reload=False,
    )

    assert isinstance(public, FastAPI)
    assert isinstance(admin, FastAPI)
    for app in (public, admin):
        binding = app.state.appctx_binding
        assert isinstance(binding, AppContextBinding)
        assert binding.appctx is appctx
        assert app.state.di_container is container
        assert app.dependency_overrides == {}


def test_reload_api_targets_create_one_root_inside_each_child_process() -> None:
    """Reload mode retains process-local app factories instead of parent objects."""
    config = Config.model_construct()
    appctx = AppContext(config)
    container = create_container(appctx)

    public, admin = _create_api_targets(
        config,
        appctx=appctx,
        container=container,
        reload=True,
    )

    assert public == "devserver:public_app"
    assert admin == "devserver:admin_app"


@pytest.mark.asyncio
async def test_devserver_resources_start_runtime_control_before_app_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local composition starts Runtime Control before Worker dependencies."""
    events: list[str] = []
    config = Config.model_construct()
    container = create_autospec(di.Container, instance=True, spec_set=True)
    runtime_control_settings = MagicMock()

    @asynccontextmanager
    async def fake_runtime_control_lifespan(
        settings: object,
        *,
        local_stores: object,
    ) -> AsyncIterator[None]:
        assert settings is runtime_control_settings
        assert local_stores is None
        events.append("runtime-control-start")
        yield
        events.append("runtime-control-stop")

    @asynccontextmanager
    async def fake_run_with_container(
        supplied_config: Config,
    ) -> AsyncIterator[di.Container]:
        assert supplied_config is config
        events.append("app-container-start")
        yield container
        events.append("app-container-stop")

    monkeypatch.setattr(
        devserver,
        "RuntimeControlSettings",
        lambda: runtime_control_settings,
    )
    monkeypatch.setattr(
        devserver,
        "runtime_control_server_lifespan",
        fake_runtime_control_lifespan,
    )
    monkeypatch.setattr(devserver, "run_with_container", fake_run_with_container)

    async with _run_devserver_resources(config) as actual:
        assert actual is container
        assert events == ["runtime-control-start", "app-container-start"]

    assert events == [
        "runtime-control-start",
        "app-container-start",
        "app-container-stop",
        "runtime-control-stop",
    ]


def test_memory_mode_rejects_reload_before_creating_api_roots() -> None:
    config = Config.model_construct(session_broker_backend="memory")
    appctx = AppContext(config)
    container = create_container(appctx)
    with pytest.raises(ValueError, match="reload child"):
        _create_api_targets(config, appctx=appctx, container=container, reload=True)


@pytest.mark.asyncio
async def test_memory_devserver_passes_exact_application_stores_to_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = Config.from_settings(
        Settings(
            _env_file=None,
            rdb_host="unused",
            rdb_user="unused",
            rdb_db_name="unused",
            auth_jwt_secret_key="synthetic",
            credential_encryption_key="synthetic",
            session_broker_backend="memory",
        )
    )
    captured: list[LocalRuntimeStores] = []
    settings = RuntimeControlSettings.model_construct()

    @asynccontextmanager
    async def control_lifespan(
        supplied: RuntimeControlSettings,
        *,
        local_stores: LocalRuntimeStores | None,
    ) -> AsyncIterator[None]:
        assert local_stores is not None
        assert supplied.session_broker_backend == "memory"
        assert supplied.runtime_control_transfer_backend == "memory"
        assert supplied.runtime_control_workspace_upload_backend == "memory"
        assert supplied.runtime_control_web_capacity_backend == "memory"
        captured.append(local_stores)
        yield

    monkeypatch.setattr(devserver, "RuntimeControlSettings", lambda: settings)
    monkeypatch.setattr(devserver, "runtime_control_server_lifespan", control_lifespan)
    async with _run_devserver_resources(config) as container:
        assert captured[0].coordination is await container.solve(
            get_runtime_coordination_store
        )
        assert captured[0].terminal is await container.solve(
            get_runtime_terminal_coordination_store
        )
        broker = await container.solve(get_broker)
        worker = await container.solve(get_worker_broker)
        await broker.send_message(SessionWakeUp("co-located"))
        assert await worker.receive_messages() == [SessionWakeUp("co-located")]
