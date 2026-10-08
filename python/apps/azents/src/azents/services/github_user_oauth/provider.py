"""Injectable GitHub SDK operations for user-account orchestration."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.github_auth import GitHubClientFactory, create_github_client
from azents.core.github_user_auth import (
    GitHubUserAccessPage,
    GitHubUserAppIdentity,
    GitHubUserIdentity,
    GitHubUserToken,
    exchange_user_code,
    get_app_registration,
    get_user_identity,
    list_user_access,
    revoke_user_token,
)
from azents.core.github_user_testenv import github_user_testenv_client_factory


@dataclasses.dataclass(frozen=True)
class GitHubUserProvider:
    """Provider transport collaborator, supplied at the composition boundary."""

    client_factory: GitHubClientFactory

    async def exchange(
        self,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> GitHubUserToken:
        """Exchange one code without implicit retry or secret normalization."""
        return await exchange_user_code(
            client_id=client_id,
            client_secret=client_secret,
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
            client_factory=self.client_factory,
        )

    async def identity(self, token: str) -> GitHubUserIdentity:
        """Read provider-verified account identity."""
        return await get_user_identity(token, client_factory=self.client_factory)

    async def app(self, jwt_token: str) -> GitHubUserAppIdentity:
        """Read authenticated App and OAuth client binding."""
        return await get_app_registration(jwt_token, client_factory=self.client_factory)

    async def access(
        self, token: str, *, app_id: int, cursor: str | None
    ) -> GitHubUserAccessPage:
        """Observe one bounded page of App/account repository readiness."""
        return await list_user_access(
            token, app_id=app_id, cursor=cursor, client_factory=self.client_factory
        )

    async def revoke(self, *, client_id: str, client_secret: str, token: str) -> None:
        """Attempt exact-token revocation and expose expected failure to its caller."""
        await revoke_user_token(
            client_id=client_id,
            client_secret=client_secret,
            token=token,
            client_factory=self.client_factory,
        )


def get_github_user_provider(
    config: Annotated[Config, Depends(get_config)],
) -> GitHubUserProvider:
    """Compose the production provider with the supported SDK client factory."""
    base_url = config.testenv_github_platform_validation_base_url
    factory = (
        github_user_testenv_client_factory(base_url)
        if config.testenv_api_enabled and base_url is not None
        else create_github_client
    )
    return GitHubUserProvider(client_factory=factory)
