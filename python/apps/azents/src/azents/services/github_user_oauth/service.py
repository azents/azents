"""Sequence fail-closed user authorization and fail-open token cleanup."""

import asyncio
import dataclasses
import datetime
import logging
import secrets
from typing import Annotated
from urllib.parse import quote, urlencode

import jwt
from fastapi import Depends
from pydantic import ConfigDict, TypeAdapter, ValidationError

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.github_auth import create_github_app_jwt
from azents.core.github_credentials import (
    GitHubSecrets,
    GitHubSecretsAppPlatformUser,
    GitHubSecretsAppUser,
)
from azents.core.github_user_auth import (
    GitHubUserAccessPage,
    GitHubUserProviderError,
    GitHubUserTokenRejected,
)
from azents.core.github_user_oauth import (
    GitHubUserAttempt,
    GitHubUserCandidate,
    GitHubUserConnection,
    GitHubUserConnectionStatus,
    GitHubUserConnectionSummary,
    GitHubUserContext,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
    GitHubUserRegistration,
    GitHubUserRequester,
    GitHubUserRevocation,
)
from azents.core.oauth2 import generate_pkce_pair
from azents.repos.github_user_oauth.operations import GitHubUserOAuthOperationRepository
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.github_user_oauth.data import (
    GitHubSetupAvailability,
    GitHubUserCandidateSummary,
    GitHubUserConnectOutput,
    GitHubUserStatusOutput,
)
from azents.services.github_user_oauth.provider import (
    GitHubUserProvider,
    get_github_user_provider,
)
from azents.utils.logging import sanitized_exception_info

logger = logging.getLogger(__name__)
_REVOCATION_TIMEOUT_SECONDS = 5.0


@dataclasses.dataclass(frozen=True)
class _PreparedRegistration:
    """Transient authenticated App material, never a response object."""

    registration: GitHubUserRegistration
    private_key: str = dataclasses.field(repr=False)


def project_connection(connection: GitHubUserConnection) -> GitHubUserConnectionSummary:
    """Project only allowlisted metadata from an active connection."""
    return GitHubUserConnectionSummary(
        id=connection.id,
        account_id=connection.account_id,
        account_login=connection.account_login,
        account_avatar_url=connection.account_avatar_url,
        app_id=connection.registration.app_id,
        source=connection.registration.source,
        status=connection.status,
        failure_reason=connection.failure_reason,
    )


@dataclasses.dataclass(frozen=True)
class GitHubUserOAuthService:
    """Manage authorization through completed operations and bounded SDK calls."""

    repository: Annotated[
        GitHubUserOAuthOperationRepository, Depends(GitHubUserOAuthOperationRepository)
    ]
    config: Annotated[Config, Depends(get_config)]
    platform_runtime: Annotated[PlatformGitHubAppRuntimeService, Depends()]
    provider: Annotated[GitHubUserProvider, Depends(get_github_user_provider)]

    def callback_url(self) -> str:
        """Return the one registered callback, not a requester-controlled URL."""
        if not self.config.web_url:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.INVALID,
                "Web URL is not configured for GitHub user authorization.",
            )
        return f"{self.config.web_url.rstrip('/')}/oauth/github/callback"

    async def availability(
        self,
        *,
        user_id: str,
        session_id: str,
        workspace_id: str,
        agent_id: str | None,
    ) -> GitHubSetupAvailability:
        """Resolve redacted local registration after exact management admission."""
        await self.repository.authorize_scope(
            user_id=user_id,
            session_id=session_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        platform = await self.platform_runtime.resolve()
        values = (
            platform.app_id,
            platform.client_id,
            platform.private_key,
            platform.client_secret,
        )
        if all(value is None for value in values):
            status = "absent"
        elif all(value is not None and bool(value) for value in values):
            status = "configured"
        else:
            status = "incomplete"
        return GitHubSetupAvailability(
            platform=status,
            callback_url=(
                f"{self.config.web_url.rstrip('/')}/oauth/github/callback"
                if self.config.web_url
                else None
            ),
        )

    async def status(self, requester: GitHubUserRequester) -> GitHubUserStatusOutput:
        """Read saved connection identity under the setup management boundary."""
        context = await self.repository.read_context(requester=requester)
        return GitHubUserStatusOutput(
            connection=(
                project_connection(context.connection)
                if context.connection is not None
                else None
            )
        )

    async def _registration(self, context: GitHubUserContext) -> _PreparedRegistration:
        """Resolve one selected App registration without copying Platform secrets."""
        if context.toolkit.toolkit_type != "github":
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.INVALID, "Toolkit is not a GitHub Toolkit."
            )
        return await self.prepare_registration(
            credentials_json=context.toolkit.credentials,
            revision=context.toolkit.revision,
        )

    async def prepare_registration(
        self, *, credentials_json: str | None, revision: int
    ) -> _PreparedRegistration:
        """Resolve a selected registration for admitted creation or reconnect."""
        try:
            credentials = TypeAdapter(
                GitHubSecrets, config=ConfigDict(hide_input_in_errors=True)
            ).validate_json(credentials_json or "null")
        except ValidationError:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.INVALID,
                "GitHub user App registration is incomplete.",
            ) from None
        if isinstance(credentials, GitHubSecretsAppPlatformUser):
            platform = await self.platform_runtime.resolve()
            if (
                platform.app_id != credentials.app_id
                or not platform.client_id
                or not platform.client_secret
                or not platform.private_key
            ):
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.INVALID,
                    "Selected Platform GitHub App is unavailable or changed. "
                    "Configure the App or restart setup.",
                )
            return _PreparedRegistration(
                registration=GitHubUserRegistration(
                    source="platform_user",
                    app_id=credentials.app_id,
                    client_id=platform.client_id,
                    client_secret=platform.client_secret,
                    toolkit_revision=revision,
                    platform_generation=platform.effective_generation,
                ),
                private_key=platform.private_key,
            )
        if isinstance(credentials, GitHubSecretsAppUser):
            return _PreparedRegistration(
                registration=GitHubUserRegistration(
                    source="byoa_user",
                    app_id=credentials.app_id,
                    client_id=credentials.client_id,
                    client_secret=credentials.client_secret,
                    toolkit_revision=revision,
                    platform_generation=None,
                ),
                private_key=credentials.private_key,
            )
        raise GitHubUserOAuthError(
            GitHubUserErrorCode.INVALID,
            "Toolkit does not use GitHub App user-account authentication.",
        )

    async def connect(self, requester: GitHubUserRequester) -> GitHubUserConnectOutput:
        """Reserve a bound attempt without replacing an existing credential."""
        context = await self.repository.read_context(requester=requester)
        prepared = await self._registration(context)
        registration = prepared.registration
        try:
            jwt_token = create_github_app_jwt(registration.app_id, prepared.private_key)
        except ValueError, jwt.PyJWTError:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.INVALID,
                "GitHub App private key or identity is invalid.",
            ) from None
        app = await self.provider.app(jwt_token)
        if (
            str(app.app_id) != registration.app_id
            or app.client_id != registration.client_id
        ):
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.INVALID,
                "OAuth client credentials do not belong to the selected GitHub App.",
            )
        pkce = generate_pkce_pair()
        nonce = secrets.token_urlsafe(32)
        result = await self.repository.start(
            requester=requester,
            registration=registration,
            redirect_uri=self.callback_url(),
            nonce=nonce,
            code_verifier=pkce.code_verifier,
            expires_at=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(minutes=10),
        )
        await self.cleanup_revocations(result.revocations)
        attempt = result.attempt
        state = f"github_user.{attempt.id}.{nonce}"
        authorization_origin = "https://github.com"
        if (
            self.config.testenv_api_enabled
            and self.config.testenv_github_platform_validation_base_url is not None
        ):
            authorization_origin = (
                self.config.testenv_github_platform_validation_base_url.rstrip("/")
            )
        authorization_url = (
            authorization_origin
            + "/login/oauth/authorize?"
            + urlencode(
                {
                    "client_id": registration.client_id,
                    "redirect_uri": attempt.redirect_uri,
                    "state": state,
                    "code_challenge": pkce.code_challenge,
                    "code_challenge_method": "S256",
                }
            )
        )
        return GitHubUserConnectOutput(
            attempt_id=attempt.id,
            authorization_url=authorization_url,
            install_url=(
                f"https://github.com/apps/{quote(app.slug, safe='')}/installations/new"
            ),
        )

    async def exchange(
        self,
        requester: GitHubUserRequester,
        *,
        code: str,
        state: str,
    ) -> GitHubUserCandidateSummary:
        """Consume once and hold a received token only until verified publication."""
        parts = state.split(".")
        if len(parts) != 3 or parts[0] != "github_user" or not parts[1] or not parts[2]:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.INVALID, "GitHub OAuth state is invalid."
            )
        attempt = await self.repository.claim_exchange(
            requester=requester,
            attempt_id=parts[1],
            nonce=parts[2],
            redirect_uri=self.callback_url(),
        )
        try:
            prepared = await self._registration(
                await self.repository.read_context(requester=requester)
            )
            if prepared.registration != attempt.registration:
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.STALE,
                    "GitHub App registration changed. Restart authorization.",
                )
            client_secret = attempt.registration.client_secret
            if client_secret is None:
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.INVALID,
                    "OAuth client secret is not configured.",
                )
        except GitHubUserOAuthError:
            await self.repository.complete_failed_exchange(attempt_id=attempt.id)
            raise
        remaining = (
            attempt.expires_at - datetime.datetime.now(datetime.UTC)
        ).total_seconds()
        if remaining <= 0:
            await self.repository.complete_failed_exchange(attempt_id=attempt.id)
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.STALE, "GitHub authorization attempt has expired."
            )
        try:
            async with asyncio.timeout(min(5.0, remaining)):
                issued = await self.provider.exchange(
                    client_id=attempt.registration.client_id,
                    client_secret=client_secret,
                    code=code,
                    redirect_uri=attempt.redirect_uri,
                    code_verifier=attempt.code_verifier,
                )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            await self.repository.complete_failed_exchange(attempt_id=attempt.id)
            raise GitHubUserProviderError(
                reason="provider_unavailable", status_code=None
            ) from None
        except GitHubUserProviderError:
            await self.repository.complete_failed_exchange(attempt_id=attempt.id)
            raise
        except GitHubUserTokenRejected as error:
            await self.repository.complete_failed_exchange(attempt_id=attempt.id)
            if error.issued_token is not None:
                await self._discard_received(attempt, error.issued_token)
            message = (
                "GitHub returned an expiring user token. Disable user-to-server "
                "token expiration in the selected App and restart authorization."
                if error.reason == "expiring_token"
                else "GitHub did not return a supported authorization. Check the "
                "selected App registration and restart authorization."
            )
            raise GitHubUserOAuthError(GitHubUserErrorCode.INVALID, message) from None
        try:
            identity = await self.provider.identity(issued.access_token)
            current = await self._registration(
                await self.repository.read_context(requester=requester)
            )
            review = await self.repository.store_review(
                requester=requester,
                attempt_id=attempt.id,
                candidate=GitHubUserCandidate(
                    access_token=issued.access_token,
                    account_id=identity.account_id,
                    account_login=identity.login,
                    account_avatar_url=identity.avatar_url,
                ),
                registration=current.registration,
            )
        except asyncio.CancelledError:
            raise
        except GitHubUserProviderError, GitHubUserOAuthError, TimeoutError:
            await self.repository.complete_failed_exchange(attempt_id=attempt.id)
            await self._discard_received(attempt, issued.access_token)
            raise
        return self._project_candidate(review)

    @staticmethod
    def _project_candidate(attempt: GitHubUserAttempt) -> GitHubUserCandidateSummary:
        """Expose verified identity and use scope, not candidate credentials."""
        candidate = attempt.candidate
        if candidate is None:
            raise RuntimeError("GitHub review candidate is missing.")
        return GitHubUserCandidateSummary(
            attempt_id=attempt.id,
            account_id=candidate.account_id,
            account_login=candidate.account_login,
            account_avatar_url=candidate.account_avatar_url,
            app_id=attempt.registration.app_id,
            source=attempt.registration.source,
            sharing_scope=(
                "agent_only"
                if attempt.requester.agent_id is not None
                else "workspace_shared"
            ),
        )

    async def review(
        self, requester: GitHubUserRequester, *, attempt_id: str
    ) -> GitHubUserCandidateSummary:
        """Read verified details after a fixed popup completion event."""
        attempt = await self.repository.read_review(
            requester=requester, attempt_id=attempt_id
        )
        prepared = await self._registration(
            await self.repository.read_context(requester=requester)
        )
        if prepared.registration != attempt.registration:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.STALE,
                "GitHub App registration changed. Restart authorization.",
            )
        return self._project_candidate(attempt)

    async def confirm(
        self, requester: GitHubUserRequester, *, attempt_id: str
    ) -> GitHubUserConnectionSummary:
        """Publish a current candidate, then attempt its old token's revocation."""
        prepared = await self._registration(
            await self.repository.read_context(requester=requester)
        )
        result = await self.repository.confirm(
            requester=requester,
            attempt_id=attempt_id,
            registration=prepared.registration,
        )
        await self.cleanup_revocations(result.revocations)
        return project_connection(result.connection)

    async def cancel(self, requester: GitHubUserRequester, *, attempt_id: str) -> None:
        """Remove the initiating attempt and attempt cleanup of its known token."""
        revocations = await self.repository.cancel(
            requester=requester, attempt_id=attempt_id
        )
        await self.cleanup_revocations(revocations)

    async def disconnect(self, requester: GitHubUserRequester) -> None:
        """Remove local authority; provider failure cannot restore or block it."""
        context = await self.repository.read_context(requester=requester)
        registration = None
        if context.connection is not None:
            try:
                prepared = await self._registration(context)
            except GitHubUserOAuthError:
                # Missing registration does not keep a retired token executable.
                registration = None
            else:
                registration = prepared.registration
        revocations = await self.repository.disconnect(
            requester=requester, registration=registration
        )
        await self.cleanup_revocations(revocations)

    async def _discard_received(self, attempt: GitHubUserAttempt, token: str) -> None:
        """Use captured facts after stale/removed setup without retaining cleanup."""
        revocation = await self.repository.received_revocation(
            toolkit_id=attempt.requester.toolkit_id,
            registration=attempt.registration,
            access_token=token,
        )
        if revocation is not None:
            await self.cleanup_revocations((revocation,))

    async def cleanup_revocations(
        self, revocations: tuple[GitHubUserRevocation, ...]
    ) -> None:
        """Await bounded exact-token attempts; local completion is not proof."""
        for revocation in revocations:
            registration = revocation.registration
            try:
                async with asyncio.timeout(_REVOCATION_TIMEOUT_SECONDS):
                    client_secret = registration.client_secret
                    if registration.source == "platform_user":
                        platform = await self.platform_runtime.resolve()
                        if (
                            platform.app_id == registration.app_id
                            and platform.client_id == registration.client_id
                            and platform.client_secret is not None
                        ):
                            client_secret = platform.client_secret
                    if client_secret is None:
                        logger.warning(
                            "GitHub token revocation was not attempted: "
                            "registration unavailable; local completion is unchanged.",
                            extra={
                                "app_source": registration.source,
                                "app_id": registration.app_id,
                                "reason": "registration_unavailable",
                            },
                        )
                        continue
                    await self.provider.revoke(
                        client_id=registration.client_id,
                        client_secret=client_secret,
                        token=revocation.access_token,
                    )
            except asyncio.CancelledError:
                raise
            except (GitHubUserProviderError, TimeoutError) as error:
                logger.warning(
                    "GitHub token revocation attempt failed; "
                    "local completion is unchanged.",
                    extra={
                        "app_source": registration.source,
                        "app_id": registration.app_id,
                        "reason": (
                            error.reason
                            if isinstance(error, GitHubUserProviderError)
                            else "timeout"
                        ),
                    },
                    exc_info=sanitized_exception_info(
                        error, message="GitHub token revocation attempt failed."
                    ),
                )

    async def access(
        self, requester: GitHubUserRequester, *, cursor: str | None
    ) -> GitHubUserAccessPage:
        """Observe App/account access without a local permissions ledger."""
        context = await self.repository.read_context(requester=requester)
        connection = context.connection
        if (
            connection is None
            or connection.status is not GitHubUserConnectionStatus.CONNECTED
        ):
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.INVALID, "GitHub user authorization is required."
            )
        prepared = await self._registration(context)
        registration = prepared.registration
        if (
            registration.app_id != connection.registration.app_id
            or registration.client_id != connection.registration.client_id
            or registration.source != connection.registration.source
        ):
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.STALE,
                "GitHub App identity changed. Reauthorize the Toolkit.",
            )
        try:
            return await self.provider.access(
                connection.access_token,
                app_id=int(registration.app_id),
                cursor=cursor,
            )
        except ValueError:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.INVALID,
                "GitHub access continuation cursor is invalid.",
            ) from None
        except GitHubUserProviderError as error:
            if error.reason == "authentication":
                await self.repository.mark_reconnect_required(
                    requester=requester,
                    connection_id=connection.id,
                    reason="authentication_failed",
                )
            raise
