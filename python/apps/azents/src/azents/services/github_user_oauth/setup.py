"""Management-only GitHub identity observations with no publication authority."""

import dataclasses
from typing import Annotated, assert_never

import jwt
from fastapi import Depends

from azents.core.github_auth import create_github_app_jwt
from azents.core.github_setup import (
    GitHubAppSetupVerification,
    GitHubPATSetupVerification,
    GitHubPlatformSetupVerification,
    GitHubSetupAppOutput,
    GitHubSetupAppVerifiedIdentity,
    GitHubSetupConnectivity,
    GitHubSetupInstallationObservation,
    GitHubSetupTransport,
    GitHubSetupUserIdentity,
    GitHubSetupVerificationOutput,
    GitHubSetupVerificationRequest,
)
from azents.core.github_user_auth import GitHubUserProviderError
from azents.core.github_user_creation import GitHubUserCreationSubject
from azents.core.github_user_oauth import GitHubUserErrorCode, GitHubUserOAuthError
from azents.core.mcp_transport import test_mcp_transport
from azents.repos.github_user_oauth.setup import GitHubSetupRepository
from azents.repos.toolkit_operations.data import PlatformToolkitAuthority
from azents.services.github_platform_system_setting.runtime import (
    ResolvedPlatformGitHubApp,
)
from azents.services.github_user_oauth.service import GitHubUserOAuthService


@dataclasses.dataclass(frozen=True)
class GitHubSetupService:
    """Reuse current scope, SDK factory and registration resolution at each boundary."""

    oauth: Annotated[GitHubUserOAuthService, Depends()]
    repository: Annotated[GitHubSetupRepository, Depends()]

    async def _authorize(self, subject: GitHubUserCreationSubject) -> None:
        await self.oauth.repository.authorize_scope(**dataclasses.asdict(subject))

    @staticmethod
    def _jwt(app_id: str, private_key: str) -> str:
        try:
            return create_github_app_jwt(app_id, private_key)
        except ValueError, jwt.PyJWTError:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.INVALID,
                "GitHub App private key or identity is invalid.",
            ) from None

    async def _recheck_platform(self, platform: ResolvedPlatformGitHubApp) -> None:
        current = await self.oauth.platform_runtime.resolve()
        if current != platform:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.STALE, "Platform GitHub App changed. Restart setup."
            )

    async def app(self, subject: GitHubUserCreationSubject) -> GitHubSetupAppOutput:
        await self._authorize(subject)
        platform = await self.oauth.platform_runtime.resolve()
        if all(
            value is None
            for value in (
                platform.app_id,
                platform.client_id,
                platform.private_key,
                platform.client_secret,
            )
        ):
            await self._authorize(subject)
            await self._recheck_platform(platform)
            return GitHubSetupAppOutput(app=None)
        if not platform.setup_ready(web_url=self.oauth.config.web_url):
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.INVALID, "Platform GitHub App setup is incomplete."
            )
        if platform.app_id is None or platform.private_key is None:
            raise AssertionError(
                "Locally ready Platform registration must contain App keys."
            )
        app = await self.oauth.provider.setup_app(
            self._jwt(platform.app_id, platform.private_key), app_id=platform.app_id
        )
        await self._authorize(subject)
        await self._recheck_platform(platform)
        return GitHubSetupAppOutput(app=app)

    async def _connectivity(
        self, token: str, transport: GitHubSetupTransport
    ) -> GitHubSetupConnectivity:
        config = self.oauth.config
        server_url = "https://api.githubcopilot.com/mcp/"
        if (
            config.testenv_api_enabled
            and config.testenv_github_platform_validation_base_url is not None
        ):
            server_url = (
                config.testenv_github_platform_validation_base_url.rstrip("/") + "/mcp"
            )
        result = await test_mcp_transport(
            server_url,
            {"Authorization": f"Bearer {token}"},
            transport.timeout,
            proxy_url=config.mcp_proxy_url,
        )
        # MCP/provider messages can contain raw response text. Only the factual
        # status crosses the setup boundary, not provider diagnostics or tool names.
        return GitHubSetupConnectivity(
            status="ready" if result.success else "failed",
            message="MCP verified; repository access remains provider-controlled."
            if result.success
            else "MCP connection could not be verified. Check access and retry.",
        )

    async def verify(
        self,
        subject: GitHubUserCreationSubject,
        request: GitHubSetupVerificationRequest,
    ) -> GitHubSetupVerificationOutput:
        await self._authorize(subject)
        platform: ResolvedPlatformGitHubApp | None = None
        platform_authority: PlatformToolkitAuthority | None = None
        if isinstance(request, GitHubPATSetupVerification):
            user = await self.oauth.provider.identity(request.token)
            connectivity = await self._connectivity(request.token, request.transport)
            await self._authorize(subject)
            return GitHubSetupVerificationOutput(
                identity=GitHubSetupUserIdentity(
                    type="user",
                    id=user.account_id,
                    login=user.login,
                    avatar_url=user.avatar_url,
                ),
                installations=[],
                connectivity=connectivity,
            )
        match request:
            case GitHubAppSetupVerification():
                app_id, private_key = request.app_id, request.private_key
            case GitHubPlatformSetupVerification():
                platform = await self.oauth.platform_runtime.resolve()
                if not platform.setup_ready(web_url=self.oauth.config.web_url):
                    raise GitHubUserOAuthError(
                        GitHubUserErrorCode.INVALID,
                        "Platform GitHub App setup is unavailable.",
                    )
                if platform.app_id is None or platform.private_key is None:
                    raise AssertionError(
                        "Locally ready Platform App must contain keys."
                    )
                app_id, private_key = platform.app_id, platform.private_key
                platform_authority = PlatformToolkitAuthority(
                    app_id=app_id,
                    app_id_source=platform.app_id_source,
                    user_id=subject.user_id,
                    installation_ids=frozenset(
                        int(identifier) for identifier in request.installation_ids
                    ),
                )
                await self.repository.authorize_platform(subject, platform_authority)
            case _:
                assert_never(request)
        token = self._jwt(app_id, private_key)
        app = await self.oauth.provider.setup_app(token, app_id=app_id)
        installations: list[GitHubSetupInstallationObservation] = []
        for installation_id in request.installation_ids:
            try:
                installation = await self.oauth.provider.setup_installation(
                    token, app_id=app_id, installation_id=installation_id
                )
            except GitHubUserProviderError as error:
                if error.reason == "invalid_response":
                    raise
                installations.append(
                    GitHubSetupInstallationObservation(
                        installation_id=installation_id,
                        account_login=None,
                        account_type=None,
                        account_avatar_url=None,
                        status="denied"
                        if error.reason in ("authentication", "target_denied")
                        else "unavailable",
                        message="Installation not verified. Remove it or retry.",
                    )
                )
            else:
                installations.append(
                    GitHubSetupInstallationObservation(
                        installation_id=str(installation.installation_id),
                        account_login=installation.account_login,
                        account_type=installation.account_type,
                        account_avatar_url=installation.account_avatar_url,
                        status="ready",
                        message="Installation verified; repository coverage unknown.",
                    )
                )
        connectivity = GitHubSetupConnectivity(
            status="failed",
            message="Every selected installation must be verified before continuing.",
        )
        if all(item.status == "ready" for item in installations):
            if platform_authority is not None:
                await self.repository.authorize_platform(subject, platform_authority)
            try:
                issued = await self.oauth.provider.setup_installation_token(
                    token, installation_id=request.installation_ids[0]
                )
            except GitHubUserProviderError as error:
                if error.reason == "invalid_response":
                    raise
                connectivity = GitHubSetupConnectivity(
                    status="failed",
                    message="Installation MCP credential unavailable. Retry.",
                )
            else:
                connectivity = await self._connectivity(
                    issued.access_token, request.transport
                )
        await self._authorize(subject)
        if platform is not None:
            await self._recheck_platform(platform)
        if platform_authority is not None:
            await self.repository.authorize_platform(subject, platform_authority)
        return GitHubSetupVerificationOutput(
            identity=GitHubSetupAppVerifiedIdentity(type="app", **app.model_dump()),
            installations=installations,
            connectivity=connectivity,
        )
