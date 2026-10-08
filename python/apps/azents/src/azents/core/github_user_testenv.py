"""Credential-free testenv routing at the supported GitHub SDK transport boundary."""

import httpx
from githubkit import BaseAuthStrategy, GitHub, UnauthAuthStrategy

from azents.core.github_auth import GitHubClientFactory


class GitHubUserTestenvTransport(httpx.AsyncBaseTransport):
    """Keep synthetic SDK requests inside one explicitly configured local fixture."""

    def __init__(self, base_url: str) -> None:
        self.origin = httpx.URL(base_url.rstrip("/"))
        self.transport = httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host not in {"api.github.com", "github.com"}:
            raise ValueError("Unexpected host in GitHub user testenv SDK request.")
        original = request.url
        request.url = self.origin.copy_with(
            path=original.path, query=original.query or None
        )
        request.headers["Host"] = self.origin.netloc.decode()
        return await self.transport.handle_async_request(request)

    async def aclose(self) -> None:
        await self.transport.aclose()


def github_user_testenv_client_factory(base_url: str) -> GitHubClientFactory:
    """Create operation-owned clients only for the configured synthetic fixture."""

    def create(auth: BaseAuthStrategy | None) -> GitHub[BaseAuthStrategy]:
        return GitHub[BaseAuthStrategy](
            auth=auth if auth is not None else UnauthAuthStrategy(),
            async_transport=GitHubUserTestenvTransport(base_url),
            timeout=5.0,
            trust_env=False,
            auto_retry=False,
            http_cache=False,
            follow_redirects=False,
        )

    return create
