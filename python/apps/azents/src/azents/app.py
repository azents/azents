"""FastAPI app creation utilities."""

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from azcommon import di
from fastapi import FastAPI
from starlette.types import Lifespan

from azents.api import admin, internal, public, testenv
from azents.consts import PROJECT_ROOT
from azents.core.config import Config
from azents.core.deps import get_appctx
from azents.services.github_platform_system_setting.binding import (
    PlatformGitHubAppBindingMigration,
)
from azents.services.system_bootstrap.service import SystemBootstrapService
from azents.utils.appctx import AppContext
from azents.utils.fastapi.route import as_route_mounter, generate_short_operation_id

logger = logging.getLogger(__name__)

PUBLIC_OPENAPI_SPEC_PATH = PROJECT_ROOT / "specs" / "public" / "openapi.json"
ADMIN_OPENAPI_SPEC_PATH = PROJECT_ROOT / "specs" / "admin" / "openapi.json"


def create_dummy_public_app() -> FastAPI:
    """Create a Public API dummy app without runtime settings.

    Used mainly when dumping the OpenAPI spec.
    """
    app = FastAPI(
        title="Azents Public API",
        description="Public read-only API server for Azents",
        generate_unique_id_function=generate_short_operation_id,
    )
    public.mount(as_route_mounter(app))
    return app


def create_dummy_admin_app() -> FastAPI:
    """Create an Admin API dummy app without runtime settings.

    Used mainly when dumping the OpenAPI spec.
    """
    app = FastAPI(
        title="Azents Admin API",
        description="Admin CRUD API server for Azents",
        generate_unique_id_function=generate_short_operation_id,
    )
    admin.mount(as_route_mounter(app))
    return app


def dump_openapi_spec(dest: str | Path, app: FastAPI) -> None:
    """Dump the OpenAPI spec to a JSON file."""
    openapi = app.openapi()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(openapi, indent=2, ensure_ascii=False) + "\n"
    if dest.exists() and dest.read_text() == rendered:
        return
    dest.write_text(rendered)


def create_public_api_app(config: Config) -> FastAPI:
    """Create the Public API app.

    The public app is read-only and uses cursor pagination. It also mounts the
    ``/internal`` sub-app for cluster-internal callers such as Pod preStop
    hooks. ALB blocks external access to ``/internal/*``. The internal sub-app
    uses ``openapi_url=None`` so it is excluded from the public OpenAPI spec.

    :param config: app settings
    :return: Public API FastAPI instance
    """
    app = _create_fastapi_instance(
        config,
        title="Azents Public API",
        description="Public read-only API server for Azents",
        initialize_system_bootstrap=False,
        initialize_platform_github_binding=True,
    )
    public.mount(as_route_mounter(app))
    internal_app = _create_internal_sub_app(app)
    app.mount("/internal", internal_app)
    return app


def _create_internal_sub_app(parent: FastAPI) -> FastAPI:
    """Configure the ``/internal`` sub-app.

    OpenAPI, Swagger, and ReDoc are disabled so the routes are not exposed in
    the public spec. Dependency overrides are shared with the parent app so the
    same config and DI container are resolved.
    """
    sub_app = FastAPI(
        title="Azents Internal API",
        description="Internal cluster-local endpoints (preStop etc.)",
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        generate_unique_id_function=generate_short_operation_id,
    )
    sub_app.dependency_overrides = parent.dependency_overrides
    internal.mount(as_route_mounter(sub_app))
    return sub_app


def create_admin_api_app(config: Config) -> FastAPI:
    """Create the Admin API app (CRUD, offset/limit pagination).

    :param config: app settings
    :return: Admin API FastAPI instance
    """
    app = _create_fastapi_instance(
        config,
        title="Azents Admin API",
        description="Admin CRUD API server for Azents",
        initialize_system_bootstrap=True,
        initialize_platform_github_binding=True,
    )
    admin.mount(as_route_mounter(app))
    return app


def create_testenv_api_app(config: Config) -> FastAPI:
    """Create the Testenv API app (testenv-only devtools).

    This app is not started in production; startup fails when
    ``config.testenv_api_enabled`` is false.

    :param config: app settings
    :return: Testenv API FastAPI instance
    """
    app = _create_fastapi_instance(
        config,
        title="Azents Testenv API",
        description="Testenv-only devtools API for Azents",
        initialize_system_bootstrap=False,
        initialize_platform_github_binding=False,
    )
    testenv.mount(as_route_mounter(app))
    return app


def _create_fastapi_instance(
    config: Config,
    *,
    title: str = "Azents API",
    description: str = "Azents API Server",
    initialize_system_bootstrap: bool,
    initialize_platform_github_binding: bool,
) -> FastAPI:
    """Create a FastAPI instance.

    :param config: app settings
    :param title: app title
    :param description: app description
    :return: FastAPI instance
    """
    appctx = AppContext(config)
    container = _create_container(appctx)
    lifespan = _create_fastapi_lifespan(
        appctx,
        container,
        initialize_system_bootstrap=initialize_system_bootstrap,
        initialize_platform_github_binding=initialize_platform_github_binding,
    )

    app = FastAPI(
        title=title,
        description=description,
        lifespan=lifespan,
        docs_url="/docs/swagger",
        redoc_url="/docs/redoc",
        openapi_url="/docs/openapi.json",
        generate_unique_id_function=generate_short_operation_id,
    )
    app.dependency_overrides.update(container.dependency_overrides)
    app.dependency_overrides[di.get_container] = lambda: container

    return app


@asynccontextmanager
async def run_with_container(config: Config) -> AsyncIterator[di.Container]:
    """DI container context manager configured by Config.

    Use this when running a non-FastAPI application, such as a CLI tool.
    """
    async with (
        AppContext(config) as ctx,
        _create_container(ctx) as container,
    ):
        yield container


def _create_fastapi_lifespan(
    appctx: AppContext[Config],
    container: di.Container,
    *,
    initialize_system_bootstrap: bool,
    initialize_platform_github_binding: bool,
) -> Lifespan[FastAPI]:
    """Create a lifespan function that binds the app context lifecycle to FastAPI."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with appctx, container:
            if initialize_platform_github_binding:
                migration = await container.solve(PlatformGitHubAppBindingMigration)
                await migration.run()
            if initialize_system_bootstrap:
                service = await container.solve(SystemBootstrapService)
                await service.initialize()
            yield

    return lifespan


def _create_dependency_overrides(appctx: AppContext[Config]) -> di.DependencyOverrides:
    """Create dependency overrides."""
    return {
        get_appctx: lambda: appctx,
    }


def _create_container(
    appctx: AppContext[Config],
) -> di.Container:
    """Create the DI container."""
    overrides = _create_dependency_overrides(appctx)
    return di.Container(dependency_overrides=overrides)
