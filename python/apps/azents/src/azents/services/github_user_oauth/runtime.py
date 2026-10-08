"""Fail-closed current-row user authority for server-admitted Toolkit execution."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from pydantic import ConfigDict, TypeAdapter, ValidationError

from azents.core.github_credentials import (
    GitHubSecrets,
    GitHubSecretsAppPlatformUser,
    GitHubSecretsAppUser,
)
from azents.core.github_user_oauth import (
    GitHubUserConnection,
    GitHubUserConnectionStatus,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
)
from azents.core.github_user_runtime import (
    GitHubUserExecutionContext,
    GitHubUserExecutionState,
)
from azents.repos.github_user_oauth.runtime import GitHubUserRuntimeOperationRepository
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)

_credentials = TypeAdapter(GitHubSecrets, config=ConfigDict(hide_input_in_errors=True))


def _unavailable() -> GitHubUserOAuthError:
    return GitHubUserOAuthError(
        GitHubUserErrorCode.STALE,
        "GitHub App identity changed or is unavailable. Reauthorize this Toolkit.",
    )


@dataclasses.dataclass(frozen=True)
class GitHubUserRuntimeService:
    """Resolve each operation using Toolkit delegation rather than a user login."""

    repository: Annotated[GitHubUserRuntimeOperationRepository, Depends()]
    platform_runtime: Annotated[PlatformGitHubAppRuntimeService, Depends()]

    async def _validated_state(
        self, context: GitHubUserExecutionContext
    ) -> GitHubUserExecutionState:
        """Return exact current identity after local and current App validation."""
        state = await self.repository.load(context)
        connection = state.connection
        if connection.status is not GitHubUserConnectionStatus.CONNECTED:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.INVALID,
                "GitHub user authorization is required. Reauthorize this Toolkit.",
            )
        try:
            credentials = _credentials.validate_json(
                state.toolkit.credentials or "null"
            )
        except ValidationError:
            raise _unavailable() from None
        expected_mode = (
            "github_app_user"
            if context.source == "byoa_user"
            else "github_app_platform_user"
        )
        if state.toolkit.config.get("github_auth_type") != expected_mode:
            raise _unavailable()
        match credentials:
            case GitHubSecretsAppUser():
                source = "byoa_user"
                app_id, client_id = credentials.app_id, credentials.client_id
                if context.client_id != client_id:
                    raise _unavailable()
            case GitHubSecretsAppPlatformUser():
                source = "platform_user"
                platform = await self.platform_runtime.resolve()
                if (
                    platform.app_id != credentials.app_id
                    or not platform.client_id
                    or not platform.private_key
                    or not platform.client_secret
                ):
                    raise _unavailable()
                app_id, client_id = credentials.app_id, platform.client_id
            case _:
                raise _unavailable()
        registration = connection.registration
        if (
            source != context.source
            or app_id != context.app_id
            or registration.source != source
            or registration.app_id != app_id
            or registration.client_id != client_id
        ):
            raise _unavailable()
        return state

    async def current_connection(
        self, context: GitHubUserExecutionContext
    ) -> GitHubUserConnection:
        """Resolve the current saved execution account independently of setup."""
        return (await self._validated_state(context)).connection

    async def runtime_environment(
        self, context: GitHubUserExecutionContext
    ) -> dict[str, str]:
        """Respect current opt-in and never return an old handed-off token."""
        current = await self._validated_state(context)
        if current.toolkit.config.get("inject_runtime_environment") is not True:
            return {}
        token = current.connection.access_token
        return {"GH_TOKEN": token, "GITHUB_TOKEN": token}

    async def authentication_failed(
        self, context: GitHubUserExecutionContext, *, connection_id: str
    ) -> None:
        """Publish a definite authentication failure without reissue or fallback."""
        await self.repository.mark_authentication_failed(
            context, connection_id=connection_id
        )
