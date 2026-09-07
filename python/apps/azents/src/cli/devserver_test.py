"""Local all-in-one devserver composition tests."""

from contextlib import asynccontextmanager
from typing import AsyncIterator, cast
from unittest.mock import MagicMock

import pytest
from azcommon import di
from fastapi import FastAPI

import cli.devserver as devserver
from azents.app import _create_container
from azents.core.config import Config
from azents.core.deps import get_appctx
from azents.core.enums import JobRuntimeBackend
from azents.utils.appctx import AppContext
from cli.devserver import _create_api_targets, _run_devserver_resources


def test_non_reload_api_apps_share_root_appcontext_and_container() -> None:
    """Co-located API roles use the Worker/Scheduler process DI base."""
    config = cast(
        Config,
        MagicMock(job_runtime_backend=JobRuntimeBackend.LOCAL),
    )
    appctx = AppContext(config)
    container = _create_container(appctx)

    public, admin = _create_api_targets(
        config,
        appctx=appctx,
        container=container,
        reload=False,
    )

    assert isinstance(public, FastAPI)
    assert isinstance(admin, FastAPI)
    for app in (public, admin):
        assert app.dependency_overrides[get_appctx]() is appctx
        assert app.dependency_overrides[di.get_container]() is container


def test_reload_api_targets_create_one_root_inside_each_child_process() -> None:
    """Reload mode retains process-local app factories instead of parent objects."""
    config = cast(Config, MagicMock())
    appctx = AppContext(config)
    container = _create_container(appctx)

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
    config = cast(Config, MagicMock())
    container = cast(di.Container, MagicMock())
    runtime_control_settings = MagicMock()

    @asynccontextmanager
    async def fake_runtime_control_lifespan(
        settings: object,
    ) -> AsyncIterator[None]:
        assert settings is runtime_control_settings
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
