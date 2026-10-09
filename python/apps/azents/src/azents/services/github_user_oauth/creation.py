"""Authorize before creation; external effects follow completed DB operations."""

import asyncio
import dataclasses
import datetime
import secrets
from typing import Annotated
from urllib.parse import quote, urlencode

import jwt
from fastapi import Depends

from azents.core.github_auth import create_github_app_jwt
from azents.core.github_user_auth import (
    GitHubUserProviderError,
    GitHubUserTokenRejected,
)
from azents.core.github_user_creation import (
    GitHubUserCreationAttempt,
    GitHubUserCreationSubject,
)
from azents.core.github_user_oauth import (
    GitHubUserAttemptStatus,
    GitHubUserCandidate,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
    GitHubUserRegistration,
    GitHubUserRevocation,
)
from azents.core.oauth2 import generate_pkce_pair
from azents.repos.github_user_oauth.creation import GitHubUserCreationRepository
from azents.repos.github_user_oauth.payloads import SetupPayload
from azents.services.github_user_oauth.data import (
    GitHubUserCandidateSummary,
    GitHubUserConnectOutput,
    GitHubUserCreatedOutput,
    GitHubUserCreationReview,
)
from azents.services.github_user_oauth.service import GitHubUserOAuthService
from azents.services.toolkit import ToolkitService
from azents.services.toolkit.data import ToolkitCreateInput


@dataclasses.dataclass(frozen=True)
class GitHubUserCreationService:
    """Pending credentials are never published until explicit account confirmation."""

    repository: Annotated[GitHubUserCreationRepository, Depends()]
    oauth: Annotated[GitHubUserOAuthService, Depends()]
    toolkits: Annotated[ToolkitService, Depends()]

    async def connect(
        self, subject: GitHubUserCreationSubject, create: ToolkitCreateInput
    ) -> GitHubUserConnectOutput:
        await self.repository.authorize(subject)
        desired = await self.toolkits.prepare_user_creation(
            create, owner_agent_id=subject.agent_id
        )
        prepared = await self.oauth.prepare_registration(
            credentials_json=desired.credentials, revision=1
        )
        registration = prepared.registration
        try:
            jwt_token = create_github_app_jwt(registration.app_id, prepared.private_key)
        except ValueError, jwt.PyJWTError:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.INVALID,
                "GitHub App private key or identity is invalid.",
            ) from None
        app = await self.oauth.provider.app(jwt_token)
        if (
            str(app.app_id) != registration.app_id
            or app.client_id != registration.client_id
        ):
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.INVALID,
                "OAuth credentials do not belong to the selected GitHub App.",
            )
        pkce = generate_pkce_pair()
        nonce = secrets.token_urlsafe(32)
        result = await self.repository.start(
            subject,
            desired=desired,
            setup=SetupPayload(
                registration=registration,
                redirect_uri=self.oauth.callback_url(),
                nonce=nonce,
                code_verifier=pkce.code_verifier,
            ),
            expires_at=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(minutes=10),
        )
        await self.oauth.cleanup_revocations(result.revocations)
        origin = "https://github.com"
        config = self.oauth.config
        if (
            config.testenv_api_enabled
            and config.testenv_github_platform_validation_base_url is not None
        ):
            origin = config.testenv_github_platform_validation_base_url.rstrip("/")
        return GitHubUserConnectOutput(
            attempt_id=result.attempt.id,
            authorization_url=origin
            + "/login/oauth/authorize?"
            + urlencode(
                {
                    "client_id": registration.client_id,
                    "redirect_uri": result.attempt.redirect_uri,
                    "state": f"github_user_create.{result.attempt.id}.{nonce}",
                    "code_challenge": pkce.code_challenge,
                    "code_challenge_method": "S256",
                }
            ),
            install_url=(
                f"https://github.com/apps/{quote(app.slug, safe='')}/installations/new"
            ),
        )

    async def _current(
        self, attempt: GitHubUserCreationAttempt
    ) -> GitHubUserRegistration:
        prepared = await self.oauth.prepare_registration(
            credentials_json=attempt.desired.credentials, revision=1
        )
        if (
            prepared.registration != attempt.registration
            or attempt.redirect_uri != self.oauth.callback_url()
        ):
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.STALE,
                "GitHub creation registration or callback changed. "
                "Restart authorization.",
            )
        return prepared.registration

    async def exchange(
        self, subject: GitHubUserCreationSubject, *, code: str, state: str
    ) -> GitHubUserCreationReview:
        parts = state.split(".")
        if (
            len(parts) != 3
            or parts[0] != "github_user_create"
            or not parts[1]
            or not parts[2]
        ):
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.INVALID, "GitHub creation OAuth state is invalid."
            )
        attempt = await self.repository.claim(
            subject,
            attempt_id=parts[1],
            nonce=parts[2],
            redirect_uri=self.oauth.callback_url(),
        )
        received: str | None = None
        try:
            await self._current(attempt)
            secret = attempt.registration.client_secret
            if secret is None:
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.INVALID,
                    "GitHub OAuth client secret is unavailable.",
                )
            remaining = (
                attempt.expires_at - datetime.datetime.now(datetime.UTC)
            ).total_seconds()
            if remaining <= 0:
                raise GitHubUserOAuthError(
                    GitHubUserErrorCode.STALE, "GitHub creation authorization expired."
                )
            async with asyncio.timeout(min(5.0, remaining)):
                issued = await self.oauth.provider.exchange(
                    client_id=attempt.registration.client_id,
                    client_secret=secret,
                    code=code,
                    redirect_uri=attempt.redirect_uri,
                    code_verifier=attempt.code_verifier,
                )
                received = issued.access_token
                identity = await self.oauth.provider.identity(received)
            registration = await self._current(attempt)
            reviewed = await self.repository.stage(
                subject,
                attempt_id=attempt.id,
                registration=registration,
                candidate=GitHubUserCandidate(
                    received, identity.account_id, identity.login, identity.avatar_url
                ),
            )
        except asyncio.CancelledError:
            raise
        except GitHubUserTokenRejected as error:
            await self.repository.discard_claimed(attempt.id)
            if error.issued_token is not None:
                await self.oauth.cleanup_revocations(
                    (GitHubUserRevocation(attempt.registration, error.issued_token),)
                )
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.INVALID,
                "GitHub returned unsupported or expiring authorization. "
                "Disable user-to-server token expiration and retry.",
            ) from None
        except TimeoutError:
            await self.repository.discard_claimed(attempt.id)
            if received is not None:
                await self.oauth.cleanup_revocations(
                    (GitHubUserRevocation(attempt.registration, received),)
                )
            raise GitHubUserProviderError(
                reason="provider_unavailable", status_code=None
            ) from None
        except GitHubUserProviderError, GitHubUserOAuthError:
            await self.repository.discard_claimed(attempt.id)
            if received is not None:
                await self.oauth.cleanup_revocations(
                    (GitHubUserRevocation(attempt.registration, received),)
                )
            raise
        return self._review(reviewed)

    @staticmethod
    def _review(attempt: GitHubUserCreationAttempt) -> GitHubUserCreationReview:
        candidate = attempt.candidate
        if attempt.status is not GitHubUserAttemptStatus.REVIEW or candidate is None:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.STALE,
                "GitHub creation account is not ready for confirmation.",
            )
        desired = attempt.desired
        return GitHubUserCreationReview(
            candidate=GitHubUserCandidateSummary(
                attempt_id=attempt.id,
                account_id=candidate.account_id,
                account_login=candidate.account_login,
                account_avatar_url=candidate.account_avatar_url,
                app_id=attempt.registration.app_id,
                source=attempt.registration.source,
                sharing_scope="workspace_shared"
                if attempt.subject.agent_id is None
                else "agent_only",
            ),
            name=desired.name,
            slug=desired.slug,
            description=desired.description,
            prompt=desired.prompt,
            config=desired.config,
            enabled=desired.enabled,
            always_expose_tools=desired.always_expose_tools,
        )

    async def review(
        self, subject: GitHubUserCreationSubject, attempt_id: str
    ) -> GitHubUserCreationReview:
        attempt = await self.repository.load(subject, attempt_id)
        await self._current(attempt)
        return self._review(attempt)

    async def confirm(
        self, subject: GitHubUserCreationSubject, attempt_id: str
    ) -> GitHubUserCreatedOutput:
        attempt = await self.repository.load(subject, attempt_id)
        self._review(attempt)
        registration = await self._current(attempt)
        toolkit_id = await self.repository.confirm(
            subject, attempt_id=attempt_id, registration=registration
        )
        return GitHubUserCreatedOutput(toolkit_id=toolkit_id)

    async def cancel(self, subject: GitHubUserCreationSubject, attempt_id: str) -> None:
        await self.oauth.cleanup_revocations(
            await self.repository.cancel(subject, attempt_id)
        )
