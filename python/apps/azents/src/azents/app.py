"""FastAPI app creation utilities."""

import asyncio
import json
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from azcommon import di
from fastapi import FastAPI
from starlette.types import Lifespan

from azents.api import admin, internal, public, testenv
from azents.consts import PROJECT_ROOT
from azents.core.config import Config
from azents.core.deps import get_appctx
from azents.job_runtime.deps import get_job_runtime
from azents.services.external_channel.ingress_recovery import (
    ExternalChannelIngressRecoveryService,
)
from azents.services.runtime_provider_bootstrap.runner import (
    RuntimeProviderBootstrapRunner,
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


def create_public_api_app(
    config: Config,
    *,
    appctx: AppContext[Config] | None = None,
    container: di.Container | None = None,
) -> FastAPI:
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
        initialize_runtime_provider_bootstrap=False,
        appctx=appctx,
        container=container,
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


def create_admin_api_app(
    config: Config,
    *,
    appctx: AppContext[Config] | None = None,
    container: di.Container | None = None,
) -> FastAPI:
    """Create the Admin API app (CRUD, offset/limit pagination).

    :param config: app settings
    :return: Admin API FastAPI instance
    """
    app = _create_fastapi_instance(
        config,
        title="Azents Admin API",
        description="Admin CRUD API server for Azents",
        initialize_system_bootstrap=True,
        initialize_runtime_provider_bootstrap=True,
        appctx=appctx,
        container=container,
    )
    admin.mount(as_route_mounter(app))
    return app


def create_testenv_api_app(
    config: Config,
    *,
    appctx: AppContext[Config] | None = None,
    container: di.Container | None = None,
) -> FastAPI:
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
        initialize_runtime_provider_bootstrap=False,
        appctx=appctx,
        container=container,
    )
    testenv.mount(as_route_mounter(app))
    return app


def _create_fastapi_instance(
    config: Config,
    *,
    title: str = "Azents API",
    description: str = "Azents API Server",
    initialize_system_bootstrap: bool,
    initialize_runtime_provider_bootstrap: bool,
    appctx: AppContext[Config] | None,
    container: di.Container | None,
) -> FastAPI:
    """Create a FastAPI instance.

    :param config: app settings
    :param title: app title
    :param description: app description
    :return: FastAPI instance
    """
    if (appctx is None) != (container is None):
        raise ValueError("AppContext and DI container must be supplied together.")
    owns_resources = appctx is None
    if appctx is None:
        appctx = AppContext(config)
        container = _create_container(appctx)
    elif appctx.config is not config:
        raise ValueError("Externally owned AppContext must use the app Config.")
    assert container is not None
    lifespan = _create_fastapi_lifespan(
        appctx,
        container,
        initialize_system_bootstrap=initialize_system_bootstrap,
        initialize_runtime_provider_bootstrap=(initialize_runtime_provider_bootstrap),
        owns_resources=owns_resources,
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
        await _preload_process_services(container)
        yield container


def _create_fastapi_lifespan(
    appctx: AppContext[Config],
    container: di.Container,
    *,
    initialize_system_bootstrap: bool,
    initialize_runtime_provider_bootstrap: bool,
    owns_resources: bool,
) -> Lifespan[FastAPI]:
    """Create a lifespan with either root-owned or externally owned resources."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            if owns_resources:
                await stack.enter_async_context(appctx)
                await stack.enter_async_context(container)
            await _preload_process_services(container)
            if owns_resources:
                await stack.enter_async_context(_run_ingress_recovery(container))
            if initialize_system_bootstrap:
                service = await container.solve(SystemBootstrapService)
                await service.initialize()
            if initialize_runtime_provider_bootstrap:
                bootstrap_runner = await container.solve(RuntimeProviderBootstrapRunner)
                async with bootstrap_runner.run():
                    yield
            else:
                yield

    return lifespan


@asynccontextmanager
async def _run_ingress_recovery(
    container: di.Container,
) -> AsyncIterator[None]:
    """Run the API producer recovery scan for the lifespan."""
    shutdown_event = asyncio.Event()
    service = await container.solve(ExternalChannelIngressRecoveryService)
    task = asyncio.create_task(
        service.run(shutdown_event),
        name="external-channel-ingress-recovery",
    )
    try:
        yield
    finally:
        shutdown_event.set()
        await task


async def _preload_process_services(container: di.Container) -> None:
    """Resolve process singletons whose configuration must fail at startup."""
    await container.solve(get_job_runtime)


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
