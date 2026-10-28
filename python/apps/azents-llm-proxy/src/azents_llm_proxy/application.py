"""Compose the packaged Proxy lifespan, resolver client and narrow ASGI ingress."""

import os
import secrets
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

import litellm.proxy.proxy_server as proxy
from fastapi import FastAPI

from azents_llm_proxy import bootstrap
from azents_llm_proxy.audit import verify_core_composition
from azents_llm_proxy.authority import AuthorityClient, create_http_client
from azents_llm_proxy.config import Settings
from azents_llm_proxy.egress import ProviderClients
from azents_llm_proxy.ingress import AgentIngress
from azents_llm_proxy.privacy import install_vendor_diagnostics

_AMBIENT_PREFIXES = (
    "OPENAI_",
    "ANTHROPIC_",
    "GEMINI_",
    "GOOGLE_",
    "AWS_",
    "AZURE_",
    "XAI_",
    "OPENROUTER_",
    "CHATGPT_",
    "MOONSHOT_",
    "KIMI_",
    "LITELLM_",
    "LANGFUSE_",
    "SENTRY_",
    "OTEL_",
    "HELICONE_",
)
_AMBIENT_KEYS = frozenset(
    {"CONFIG_FILE_PATH", "WORKER_CONFIG", "DATABASE_URL", "REDIS_URL", "SSLKEYLOGFILE"}
)


def validate_environment(environment: Mapping[str, str]) -> None:
    """The independent service has no Pod-wide provider account or exporters."""
    if any(
        name in _AMBIENT_KEYS or name.startswith(_AMBIENT_PREFIXES)
        for name, value in environment.items()
        if value and not (name == "LITELLM_LOCAL_MODEL_COST_MAP" and value == "True")
    ):
        raise RuntimeError("Ambient provider or Proxy configuration is not allowed.")


def select_direct_dispatch() -> None:
    """The official loader creates an empty Router; it must never route a call."""
    if proxy.llm_router is not None and proxy.llm_router.get_model_list():
        raise RuntimeError("The inference Proxy cannot contain a model registry.")
    if proxy.prisma_client is not None:
        raise RuntimeError("The inference Proxy cannot contain a credential database.")
    if proxy.user_custom_auth is not bootstrap.authenticate:
        raise RuntimeError("The Agent authority callback is not installed.")
    if bootstrap.context.clients is None:
        raise RuntimeError("The protected inference transport is not configured.")
    proxy.llm_router = None
    proxy.llm_model_list = []


def create_application(settings: Settings) -> AgentIngress:
    """One application per process; use the original Proxy startup/shutdown."""
    validate_environment(os.environ)
    install_vendor_diagnostics()
    verify_core_composition()
    os.environ["CONFIG_FILE_PATH"] = str(bootstrap.CONFIG)
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    # The pinned Proxy boot guard requires a strong master key even with custom
    # auth. A fresh, undisclosed nonce satisfies that guard; it is never issued
    # or mounted, and every exposed route still requires online Agent authority.
    os.environ["LITELLM_MASTER_KEY"] = "sk-" + secrets.token_urlsafe(48)
    original_lifespan = proxy.app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with (
            create_http_client(settings) as client,
            ProviderClients.open(bootstrap.context) as clients,
        ):
            bootstrap.context.clients = clients
            bootstrap.configure(AuthorityClient(client, settings.resolver_key))
            try:
                async with original_lifespan(app):
                    select_direct_dispatch()
                    yield
            finally:
                bootstrap.composition.authentication = None
                bootstrap.context.clients = None

    proxy.app.router.lifespan_context = lifespan
    return AgentIngress(proxy.app, bootstrap.context)
