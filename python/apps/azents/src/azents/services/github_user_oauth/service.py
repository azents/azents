"""Sequence completed GitHub user setup operations and provider effects."""

import asyncio
import dataclasses
import datetime
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
    GitHubUserCleanup,
    GitHubUserConnection,
    GitHubUserConnectionStatus,
    GitHubUserConnectionSummary,
    GitHubUserContext,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
    GitHubUserRegistration,
    GitHubUserRequester,
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
from azents.services.github_user_oauth.exchange_owner import (
    GitHubUserExchangeOperation,
    GitHubUserExchangeOwner,
    get_github_user_exchange_owner,
)
from azents.services.github_user_oauth.provider import (
    GitHubUserProvider,
    get_github_user_provider,
)


@dataclasses.dataclass(frozen=True)
class _PreparedRegistration:
    """Transient authenticated App material, never a response object."""

    registration: GitHubUserRegistration
    private_key: str = dataclasses.field(repr=False)


@dataclasses.dataclass
class _ExchangeReceipt:
    """Retain exact received material until the owned operation settles."""

    attempt: GitHubUserAttempt | None = dataclasses.field(repr=False)
    access_token: str | None = dataclasses.field(repr=False)


def project_connection(
    connection: GitHubUserConnection, *, cleanup_pending: bool
) -> GitHubUserConnectionSummary:
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
        cleanup_pending=cleanup_pending,
    )


@dataclasses.dataclass(frozen=True)
class GitHubUserOAuthService:
    """Manage Toolkit-local user authorization without database lifetime handles."""

    repository: Annotated[
        GitHubUserOAuthOperationRepository, Depends(GitHubUserOAuthOperationRepository)
    ]
    config: Annotated[Config, Depends(get_config)]
    platform_runtime: Annotated[PlatformGitHubAppRuntimeService, Depends()]
    provider: Annotated[GitHubUserProvider, Depends(get_github_user_provider)]
    exchange_owner: Annotated[
        GitHubUserExchangeOwner, Depends(get_github_user_exchange_owner)
    ]

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
        callback = (
            f"{self.config.web_url.rstrip('/')}/oauth/github/callback"
            if self.config.web_url
            else None
        )
        return GitHubSetupAvailability(platform=status, callback_url=callback)

    async def status(self, requester: GitHubUserRequester) -> GitHubUserStatusOutput:
        """Read redacted status under the same management boundary as setup."""
        context = await self.repository.read_context(requester=requester)
        return GitHubUserStatusOutput(
            connection=(
                project_connection(
                    context.connection, cleanup_pending=context.cleanup_pending
                )
                if context.connection is not None
                else None
            ),
            cleanup_pending=context.cleanup_pending,
        )

    async def _registration(self, context: GitHubUserContext) -> _PreparedRegistration:
        """Resolve one selected App registration without copying Platform secrets."""
        if context.toolkit.toolkit_type != "github":
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.INVALID, "Toolkit is not a GitHub Toolkit."
            )
        try:
            credentials = TypeAdapter(
                GitHubSecrets, config=ConfigDict(hide_input_in_errors=True)
            ).validate_json(context.toolkit.credentials or "null")
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
                    toolkit_revision=context.toolkit.revision,
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
                    toolkit_revision=context.toolkit.revision,
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
        await self._cleanup_available(requester)
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
        attempt = await self.repository.start(
            requester=requester,
            registration=registration,
            redirect_uri=self.callback_url(),
            nonce=nonce,
            code_verifier=pkce.code_verifier,
            expires_at=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(minutes=10),
        )
        await self._cleanup_available(requester)
        state = f"github_user.{attempt.id}.{nonce}"
        authorization_url = "https://github.com/login/oauth/authorize?" + urlencode(
            {
                "client_id": registration.client_id,
                "redirect_uri": attempt.redirect_uri,
                "state": state,
                "code_challenge": pkce.code_challenge,
                "code_challenge_method": "S256",
            }
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
        """Keep the admitted exchange/capture alive when its HTTP caller disappears."""
        receipt = _ExchangeReceipt(attempt=None, access_token=None)

        async def call(
            operation: GitHubUserExchangeOperation,
        ) -> GitHubUserCandidateSummary | None:
            return await self._exchange_once(
                requester, code=code, state=state, receipt=receipt, operation=operation
            )

        async def finalize_detached() -> None:
            if receipt.attempt is not None and receipt.access_token is not None:
                await self._discard_issued(
                    receipt.attempt, receipt.access_token, "caller_cancelled"
                )

        result = await self.exchange_owner.run(call, finalize_detached)
        if result is None:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.STALE, "Authorization caller is no longer active."
            )
        return result

    async def _exchange_once(
        self,
        requester: GitHubUserRequester,
        *,
        code: str,
        state: str,
        receipt: _ExchangeReceipt,
        operation: GitHubUserExchangeOperation,
    ) -> GitHubUserCandidateSummary | None:
        """Consume once, capture before identity, and never activate on its own."""
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
        receipt.attempt = attempt
        try:
            context = await self.repository.read_context(requester=requester)
            prepared = await self._registration(context)
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
        except TimeoutError:
            await self.repository.complete_failed_exchange(attempt_id=attempt.id)
            raise GitHubUserProviderError(
                reason="provider_unavailable", status_code=None
            ) from None
        except GitHubUserProviderError:
            await self.repository.complete_failed_exchange(attempt_id=attempt.id)
            raise
        except GitHubUserTokenRejected as error:
            if error.issued_token is not None:
                receipt.access_token = error.issued_token
                await self._discard_issued(
                    attempt, error.issued_token, "token_rejected"
                )
            else:
                await self.repository.complete_failed_exchange(attempt_id=attempt.id)
            message = (
                "GitHub returned an expiring user token. Disable user-to-server "
                "token expiration in the selected App and restart authorization."
                if error.reason == "expiring_token"
                else "GitHub did not return a supported authorization. Check the "
                "selected App registration and restart authorization."
            )
            raise GitHubUserOAuthError(GitHubUserErrorCode.INVALID, message) from None
        receipt.access_token = issued.access_token
        retired = await self.repository.record_exchange_token(
            attempt_id=attempt.id,
            registration=attempt.registration,
            access_token=issued.access_token,
        )
        if retired is not None:
            await self._cleanup_one(retired, requester=requester)
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.STALE, "GitHub setup is no longer current."
            )
        if operation.detached:
            await self._discard_issued(attempt, issued.access_token, "caller_cancelled")
            return None
        try:
            identity = await self.provider.identity(issued.access_token)
        except GitHubUserProviderError:
            await self._discard_issued(attempt, issued.access_token, "identity_failed")
            raise
        if operation.detached:
            await self._discard_issued(attempt, issued.access_token, "caller_cancelled")
            return None
        candidate = GitHubUserCandidate(
            access_token=issued.access_token,
            account_id=identity.account_id,
            account_login=identity.login,
            account_avatar_url=identity.avatar_url,
        )
        try:
            current = await self._registration(
                await self.repository.read_context(requester=requester)
            )
            review = await self.repository.store_review(
                requester=requester,
                attempt_id=attempt.id,
                candidate=candidate,
                registration=current.registration,
            )
        except GitHubUserOAuthError:
            await self._discard_issued(attempt, issued.access_token, "setup_stale")
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
        """Read verified review details after a fixed popup completion event."""
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
        """Publish only a current reviewed candidate and revoke its predecessor."""
        prepared = await self._registration(
            await self.repository.read_context(requester=requester)
        )
        connection = await self.repository.confirm(
            requester=requester,
            attempt_id=attempt_id,
            registration=prepared.registration,
        )
        await self.cleanup_retry(requester)
        return project_connection(connection, cleanup_pending=False)

    async def cancel(self, requester: GitHubUserRequester, *, attempt_id: str) -> None:
        """Cancel only the initiating attempt and revoke issued candidate tokens."""
        await self.repository.cancel(requester=requester, attempt_id=attempt_id)
        await self.cleanup_retry(requester)

    async def disconnect(self, requester: GitHubUserRequester) -> None:
        """Retire local authority, then require successful single-token revocation."""
        context = await self.repository.read_context(requester=requester)
        registration = None
        if context.connection is not None:
            try:
                prepared = await self._registration(context)
            except GitHubUserOAuthError:
                # Missing registration must not keep the old token executable.
                registration = None
            else:
                registration = prepared.registration
        try:
            await self.repository.disconnect(
                requester=requester, registration=registration
            )
        except GitHubUserOAuthError as error:
            if error.code is not GitHubUserErrorCode.CLEANUP_REQUIRED:
                raise
            await self._cleanup_available(requester)
            raise
        await self.cleanup_retry(requester)

    async def cleanup_retry(self, requester: GitHubUserRequester) -> None:
        """Retry captured retired credentials under current management authority."""
        await self._cleanup_available(requester)
        await self.repository.ensure_cleanup_complete(requester=requester)

    async def _cleanup_available(self, requester: GitHubUserRequester) -> None:
        """Clean known retired tokens without claiming an unknown exchange is done."""
        retired = await self.repository.list_cleanup(requester=requester)
        for cleanup in retired:
            await self._cleanup_one(cleanup, requester=requester)

    async def _discard_issued(
        self, attempt: GitHubUserAttempt, token: str, reason: str
    ) -> None:
        """Persist and revoke a discarded issued token even after authority loss."""
        cleanup = await self.repository.retire_exchange_result(
            attempt_id=attempt.id,
            registration=attempt.registration,
            access_token=token,
            reason=reason,
        )
        if cleanup is not None:
            await self._cleanup_one(cleanup, requester=attempt.requester)

    async def _retired_token_is_invalid(self, cleanup: GitHubUserCleanup) -> bool:
        """Confirm invalidity of the captured token at GitHub's user endpoint."""
        try:
            await self.provider.identity(cleanup.access_token)
        except GitHubUserProviderError as error:
            return error.reason == "authentication" and error.status_code == 401
        return False

    async def _cleanup_one(
        self, cleanup: GitHubUserCleanup, *, requester: GitHubUserRequester | None
    ) -> None:
        """Revoke the captured token; never resolve a newer execution credential."""
        client_secret = cleanup.registration.client_secret
        if cleanup.registration.source == "platform_user":
            platform = await self.platform_runtime.resolve()
            if (
                platform.app_id == cleanup.registration.app_id
                and platform.client_id == cleanup.registration.client_id
                and platform.client_secret is not None
            ):
                client_secret = platform.client_secret
        elif requester is not None:
            try:
                prepared = await self._registration(
                    await self.repository.read_context(requester=requester)
                )
            except GitHubUserOAuthError:
                # Retired cleanup keeps its captured binding after admission loss.
                pass
            else:
                if (
                    prepared.registration.source == cleanup.registration.source
                    and prepared.registration.app_id == cleanup.registration.app_id
                    and prepared.registration.client_id
                    == cleanup.registration.client_id
                ):
                    client_secret = prepared.registration.client_secret
        if client_secret is None:
            if await self._retired_token_is_invalid(cleanup):
                await self.repository.finish_retired(cleanup_id=cleanup.id)
                return
            await self.repository.mark_retired_failure(
                cleanup_id=cleanup.id, reason="registration_unavailable"
            )
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.CLEANUP_REQUIRED,
                "GitHub token cleanup is incomplete. Restore the original App "
                "registration and retry cleanup.",
            )
        try:
            await self.provider.revoke(
                client_id=cleanup.registration.client_id,
                client_secret=client_secret,
                token=cleanup.access_token,
            )
        except GitHubUserProviderError:
            if await self._retired_token_is_invalid(cleanup):
                await self.repository.finish_retired(cleanup_id=cleanup.id)
                return
            await self.repository.mark_retired_failure(
                cleanup_id=cleanup.id, reason="provider_cleanup_failed"
            )
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.CLEANUP_REQUIRED,
                "GitHub token cleanup is incomplete. Retry cleanup.",
            ) from None
        await self.repository.finish_retired(cleanup_id=cleanup.id)

    async def access(
        self, requester: GitHubUserRequester, *, cursor: str | None
    ) -> GitHubUserAccessPage:
        """Observe App/account access without creating a local permissions ledger."""
        context = await self.repository.read_context(requester=requester)
        connection = context.connection
        if (
            connection is None
            or connection.status is not GitHubUserConnectionStatus.CONNECTED
        ):
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.INVALID,
                "GitHub user authorization is required.",
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
