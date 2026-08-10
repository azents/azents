"""Local all-in-one devserver composition tests."""

from typing import cast
from unittest.mock import MagicMock

from azcommon import di
from fastapi import FastAPI

from azents.app import _create_container
from azents.core.config import Config
from azents.core.deps import get_appctx
from azents.core.enums import JobRuntimeBackend
from azents.utils.appctx import AppContext
from cli.devserver import _create_api_targets


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
