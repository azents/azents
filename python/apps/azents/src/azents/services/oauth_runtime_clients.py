"""Composition factories for bounded OAuth refresh transports."""

import dataclasses
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx

from azents.core.chatgpt_oauth import resolve_chatgpt_oauth_token_url
from azents.services.chatgpt_oauth.client import ChatGPTOAuthClient
from azents.services.kimi_oauth.client import KimiOAuthClient
from azents.services.xai_oauth.client import XaiOAuthClient

type ChatGPTOAuthClientFactory = Callable[
    [], AbstractAsyncContextManager[ChatGPTOAuthClient]
]
type KimiOAuthClientFactory = Callable[[], AbstractAsyncContextManager[KimiOAuthClient]]
type XaiOAuthClientFactory = Callable[[], AbstractAsyncContextManager[XaiOAuthClient]]


@dataclasses.dataclass(frozen=True)
class RuntimeOAuthClientFactories:
    """Injectable per-operation transports with explicitly owned lifetimes."""

    chatgpt: ChatGPTOAuthClientFactory
    kimi: KimiOAuthClientFactory
    xai: XaiOAuthClientFactory


@asynccontextmanager
async def _chatgpt_client() -> AsyncIterator[ChatGPTOAuthClient]:
    async with httpx.AsyncClient(timeout=20.0) as http_client:
        yield ChatGPTOAuthClient(
            http_client, token_url=resolve_chatgpt_oauth_token_url()
        )


@asynccontextmanager
async def _kimi_client() -> AsyncIterator[KimiOAuthClient]:
    async with httpx.AsyncClient(timeout=20.0) as http_client:
        yield KimiOAuthClient(http_client)


@asynccontextmanager
async def _xai_client() -> AsyncIterator[XaiOAuthClient]:
    async with httpx.AsyncClient(timeout=20.0) as http_client:
        yield XaiOAuthClient(http_client)


def create_runtime_oauth_client_factories() -> RuntimeOAuthClientFactories:
    """Wire the standard provider transports at the dependency boundary."""
    return RuntimeOAuthClientFactories(
        chatgpt=_chatgpt_client, kimi=_kimi_client, xai=_xai_client
    )
