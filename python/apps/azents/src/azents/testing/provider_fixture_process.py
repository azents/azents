"""Real API and worker composition with public SDK fixtures for core E2E."""

import asyncio
import logging
import signal

from azcommon import di
from azcommon.logging import configure_logging_for_runtime
from fastapi import FastAPI

from azents.api import testenv
from azents.app import create_admin_api_app, create_public_api_app
from azents.core.config import Config
from azents.core.credentials import (
    ChatGPTOAuthSecrets,
    KimiOAuthSecrets,
    XaiOAuthSecrets,
)
from azents.engine.model_factories import get_model_sdk_factories
from azents.process_lifecycle import create_container, preload_process_services
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationWithSecrets,
)
from azents.services.llm_catalog import (
    IntegrationModelListing,
    get_integration_model_listing,
)
from azents.services.model_listing.data import ModelListingOutput
from azents.testing.deterministic_model_listing import build_deterministic_listing
from azents.testing.provider_sdk_factories import fixture_model_sdk_factories
from azents.utils.appctx import AppContext
from azents.utils.fastapi.route import as_route_mounter
from azents.worker.deps import get_health_server
from azents.worker.worker import AgentWorker

logger = logging.getLogger(__name__)


def _config() -> Config:
    """Refuse this entry point without the existing explicit testenv boundary."""
    config = Config.from_env()
    if not config.testenv_api_enabled:
        raise RuntimeError("Provider SDK fixture composition requires testenv.")
    configure_logging_for_runtime(
        runtime_env=config.runtime_env,
        inhouse_name="azents",
        sentry_dsn=config.sentry_dsn,
    )
    return config


def _configure_fixture_container(container: di.Container) -> None:
    """Override constructors before service preload, not vendor SDK methods."""
    container.dependency_overrides[get_model_sdk_factories] = (
        fixture_model_sdk_factories
    )
    container.dependency_overrides[get_integration_model_listing] = (
        fixture_integration_model_listing
    )


def fixture_integration_model_listing() -> IntegrationModelListing:
    """Keep synthetic account discovery local even before metadata is updated."""
    return _fixture_account_listing


async def _fixture_account_listing(
    integration: LLMProviderIntegrationWithSecrets,
) -> ModelListingOutput:
    secrets = integration.secrets
    if isinstance(
        secrets, ChatGPTOAuthSecrets | XaiOAuthSecrets | KimiOAuthSecrets
    ) and secrets.access_token.startswith("e2e-provider-cutover-"):
        return build_deterministic_listing(
            variant="deterministic-provider-core",
            provider=integration.provider,
            integration_id=integration.id,
        )
    return await get_integration_model_listing()(integration)


def _attach_fixture_constructors(app: FastAPI) -> FastAPI:
    """Keep the ordinary owned app lifecycle, including producer recovery."""
    candidate = app.state.di_container
    if not isinstance(candidate, di.Container):
        raise TypeError("The API composition did not provide its DI container.")
    _configure_fixture_container(candidate)
    app.dependency_overrides[get_model_sdk_factories] = fixture_model_sdk_factories
    app.dependency_overrides[get_integration_model_listing] = (
        fixture_integration_model_listing
    )
    return app


def create_public_fixture_app() -> FastAPI:
    """Serve the production public app with scoped public SDK constructor I/O."""
    return _attach_fixture_constructors(create_public_api_app(_config()))


def create_admin_fixture_app() -> FastAPI:
    """Retain the ordinary Admin/bootstrap and testenv-route composition."""
    config = _config()
    app = _attach_fixture_constructors(create_admin_api_app(config))
    testenv.mount(as_route_mounter(app))
    return app


async def run_fixture_worker() -> None:
    """Run the real worker with the same health/drain lifecycle as its CLI."""
    config = _config()
    shutdown_event = asyncio.Event()
    async with AppContext(config) as appctx, create_container(appctx) as container:
        _configure_fixture_container(container)
        await preload_process_services(container)
        worker = await container.solve(AgentWorker)
        health = await container.solve(get_health_server)

        def shutdown(sig: signal.Signals) -> None:
            logger.info(
                "Received shutdown signal, draining", extra={"signal": sig.name}
            )
            health.mark_shutting_down()
            shutdown_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, shutdown, sig)
        await health.start()
        try:
            await worker.run(shutdown_event=shutdown_event)
        finally:
            await health.stop()


if __name__ == "__main__":
    asyncio.run(run_fixture_worker())
