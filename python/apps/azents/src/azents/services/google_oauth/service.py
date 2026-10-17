"""Exact encrypted callback context and token-free Google setup orchestration."""

import asyncio
import dataclasses
import datetime
import secrets
from typing import Annotated, Literal

from cryptography.fernet import InvalidToken
from fastapi import Depends
from pydantic import BaseModel, ConfigDict, ValidationError

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.google_oauth import (
    GoogleAttempt,
    GoogleAttemptStatus,
    GoogleCandidate,
    GoogleConnectionStatus,
    GoogleFinalSettings,
    GoogleManager,
    GoogleOAuthError,
    GooglePersonalSubject,
    GooglePublication,
    GoogleReconnectSettings,
    GoogleSetup,
    GoogleSubject,
)
from azents.core.google_policy import (
    GOOGLE_TOOL_POLICY,
    GoogleTask,
    permitted_tools,
    requested_scopes,
)
from azents.core.google_system_setting import (
    GoogleApplicationRegistration,
    GoogleApplicationUnavailable,
    GooglePreparation,
)
from azents.core.oauth2 import generate_pkce_pair
from azents.core.toolkit_ownership import UserToolkitOwner
from azents.repos.google_oauth.management import GoogleOAuthRepository
from azents.services.google_application.service import GoogleApplicationService
from azents.services.google_oauth.data import (
    GOOGLE_SECURITY_NOTICE,
    GoogleCancelOutput,
    GoogleConnectInput,
    GoogleConnectionOutput,
    GoogleConnectOutput,
    GooglePublishedOutput,
    GoogleReview,
    GoogleTaskAccess,
)
from azents.services.google_oauth.provider import GoogleOAuthProvider


class _CallbackState(BaseModel):
    """Authenticated ciphertext binds purpose and exact initiating context."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    purpose: Literal["google_connection"]
    attempt_id: str
    user_id: str
    session_id: str
    workspace_id: str
    agent_id: str | None
    nonce: str


class _PersonalCallbackState(BaseModel):
    """Explicit User-global callback contract, distinct from existing shared state."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    purpose: Literal["google_personal_connection"]
    attempt_id: str
    user_id: str
    session_id: str
    owner: UserToolkitOwner
    nonce: str


@dataclasses.dataclass(frozen=True)
class GoogleOAuthService:
    """Services sequence completed DB operations around SDK-owned provider I/O."""

    repository: Annotated[GoogleOAuthRepository, Depends()]
    application: Annotated[GoogleApplicationService, Depends()]
    provider: Annotated[GoogleOAuthProvider, Depends()]
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)]

    async def _registration(self) -> GoogleApplicationRegistration:
        try:
            return await self.application.resolve()
        except GoogleApplicationUnavailable, ValidationError:
            raise GoogleOAuthError(
                "operator_setup_required", "Google operator preparation is required."
            ) from None

    async def preparation(self, subject: GoogleManager) -> GooglePreparation:
        """Managers see preparation only after exact current scope admission."""
        await self.repository.authorize(subject)
        try:
            return await self.application.preparation()
        except GoogleApplicationUnavailable:
            raise GoogleOAuthError(
                "operator_setup_required", "Verify the operator Google configuration."
            ) from None

    async def connect(
        self,
        subject: GoogleManager,
        desired: GoogleConnectInput,
        *,
        target_toolkit_id: str | None,
    ) -> GoogleConnectOutput:
        """Reserve an unpublished attempt before browser consent begins."""
        await self.repository.authorize(subject)
        registration = await self._registration()
        pkce = generate_pkce_pair()
        setup = GoogleSetup(
            client_id=registration.client_id,
            effective_generation=registration.effective_generation,
            redirect_uri=registration.redirect_uri,
            state_nonce=secrets.token_urlsafe(32),
            oidc_nonce=secrets.token_urlsafe(32),
            code_verifier=pkce.code_verifier,
            tasks=tuple(dict.fromkeys(desired.tasks)),
            timeout=desired.timeout,
            target=None,
        )
        attempt = await self.repository.start(
            subject,
            registration=registration,
            setup=setup,
            target_toolkit_id=target_toolkit_id,
        )
        callback: _CallbackState | _PersonalCallbackState
        if isinstance(subject, GooglePersonalSubject):
            callback = _PersonalCallbackState(
                purpose="google_personal_connection",
                attempt_id=attempt.id,
                user_id=subject.user_id,
                session_id=subject.session_id,
                owner=subject.owner,
                nonce=setup.state_nonce,
            )
        else:
            callback = _CallbackState(
                purpose="google_connection",
                attempt_id=attempt.id,
                user_id=subject.user_id,
                session_id=subject.session_id,
                workspace_id=subject.workspace_id,
                agent_id=subject.agent_id,
                nonce=setup.state_nonce,
            )
        state = self.cipher.encrypt(callback.model_dump_json())
        return GoogleConnectOutput(
            attempt_id=attempt.id,
            expires_at=attempt.expires_at,
            authorization_url=self.provider.authorization_url(
                setup, state, pkce.code_challenge
            ),
        )

    def _state(
        self, subject: GoogleManager, state: str
    ) -> _CallbackState | _PersonalCallbackState:
        if len(state) > 16384:
            raise GoogleOAuthError("invalid_state", "Google callback state is invalid.")
        try:
            if isinstance(subject, GooglePersonalSubject):
                personal = _PersonalCallbackState.model_validate_json(
                    self.cipher.decrypt(state)
                )
                if (
                    personal.user_id != subject.user_id
                    or personal.session_id != subject.session_id
                    or personal.owner != subject.owner
                ):
                    raise GoogleOAuthError(
                        "invalid_state", "Google callback context does not match."
                    )
                return personal
            decoded = _CallbackState.model_validate_json(self.cipher.decrypt(state))
        except InvalidToken, ValidationError, UnicodeError:
            raise GoogleOAuthError(
                "invalid_state", "Google callback state is invalid."
            ) from None
        if (
            GoogleSubject(
                decoded.user_id,
                decoded.session_id,
                decoded.workspace_id,
                decoded.agent_id,
            )
            != subject
        ):
            raise GoogleOAuthError(
                "invalid_state", "Google callback context does not match."
            )
        return decoded

    @staticmethod
    def _bound(setup: GoogleSetup, registration: GoogleApplicationRegistration) -> None:
        if (
            setup.client_id != registration.client_id
            or setup.redirect_uri != registration.redirect_uri
            or not secrets.compare_digest(
                setup.effective_generation, registration.effective_generation
            )
        ):
            raise GoogleOAuthError(
                "stale", "Google application changed. Restart setup."
            )

    async def exchange(
        self,
        subject: GoogleManager,
        *,
        code: str,
        state: str,
    ) -> GoogleReview:
        """One callback claim precedes exchange; failures erase only local candidate."""
        decoded = self._state(subject, state)
        registration = await self._registration()
        attempt = await self.repository.claim(
            subject,
            attempt_id=decoded.attempt_id,
            nonce=decoded.nonce,
            registration=registration,
        )
        setup = attempt.setup
        if setup is None:
            raise AssertionError("Claimed Google setup is missing.")
        try:
            self._bound(setup, registration)
            remaining = (
                attempt.expires_at - datetime.datetime.now(datetime.UTC)
            ).total_seconds()
            if remaining <= 0:
                raise GoogleOAuthError("expired", "Google authorization expired.")
            async with asyncio.timeout(min(20.0, remaining)):
                receipt = await self.provider.exchange(registration, setup, code)
                identity = await self.provider.identity(
                    receipt, setup.client_id, setup.oidc_nonce
                )
            current = await self._registration()
            self._bound(setup, current)
            reviewed = await self.repository.stage(
                subject,
                attempt_id=attempt.id,
                registration=current,
                candidate=GoogleCandidate(
                    identity=identity,
                    tokens=receipt.tokens(),
                    requested_scopes=requested_scopes(setup.tasks),
                ),
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            await self.repository.discard_claimed(attempt.id)
            raise GoogleOAuthError(
                "provider_unavailable", "Google authorization outcome is uncertain."
            ) from None
        except GoogleOAuthError:
            await self.repository.discard_claimed(attempt.id)
            raise
        return self._review(reviewed)

    @staticmethod
    def _accesses(
        tasks: tuple[GoogleTask, ...],
        scopes: tuple[str, ...] | None,
    ) -> tuple[GoogleTaskAccess, ...]:
        accesses: list[GoogleTaskAccess] = []
        for task in tasks:
            policies = [item for item in GOOGLE_TOOL_POLICY if item.task is task]
            service = policies[0].service
            known = {item.name for item in policies}
            allowed = permitted_tools((task,), scopes, service)
            status: Literal["permitted", "partial", "not_granted", "unknown"]
            if scopes is None:
                status = "unknown"
            elif not allowed:
                status = "not_granted"
            elif allowed == known:
                status = "permitted"
            else:
                status = "partial"
            accesses.append(
                GoogleTaskAccess(
                    task=task,
                    service=service,
                    status=status,
                    permitted_tools=tuple(sorted(allowed)),
                    unavailable_tools=tuple(sorted(known - allowed)),
                )
            )
        return tuple(accesses)

    @staticmethod
    def _review(attempt: GoogleAttempt) -> GoogleReview:
        setup, candidate = attempt.setup, attempt.candidate
        if (
            setup is None
            or candidate is None
            or attempt.status is not GoogleAttemptStatus.REVIEW
        ):
            raise GoogleOAuthError("stale", "Google account is not ready for review.")
        scopes = candidate.tokens.granted_scopes
        accesses = GoogleOAuthService._accesses(setup.tasks, scopes)
        usable = any(item.permitted_tools for item in accesses)
        result: Literal["full", "partial", "none", "unknown"]
        if scopes is None:
            result = "unknown"
        elif not usable:
            result = "none"
        elif all(item.status == "permitted" for item in accesses):
            result = "full"
        else:
            result = "partial"
        renewable = bool(candidate.tokens.refresh_token)
        return GoogleReview(
            attempt_id=attempt.id,
            expires_at=attempt.expires_at,
            identity=candidate.identity,
            client_id=setup.client_id,
            ownership=(
                "personal"
                if isinstance(attempt.subject, GooglePersonalSubject)
                else "workspace_shared"
                if attempt.subject.agent_id is None
                else "agent_only"
            ),
            reconnect_toolkit_id=None
            if setup.target is None
            else setup.target.toolkit_id,
            requested_tasks=setup.tasks,
            timeout=setup.timeout,
            tasks=tuple(accesses),
            grant_result=result,
            renewable=renewable,
            can_confirm=usable
            and renewable
            and (candidate.tokens.expires_at > datetime.datetime.now(datetime.UTC)),
            service_access_verified=False,
            security_notice=GOOGLE_SECURITY_NOTICE,
        )

    async def review(self, subject: GoogleManager, attempt_id: str) -> GoogleReview:
        attempt = await self.repository.load(subject, attempt_id)
        if attempt.setup is None:
            raise GoogleOAuthError("stale", "Google setup has no unpublished review.")
        self._bound(attempt.setup, await self._registration())
        return self._review(attempt)

    @staticmethod
    def _publication(result: GooglePublication) -> GooglePublishedOutput:
        return GooglePublishedOutput(
            toolkit_id=result.toolkit_id,
            connection_id=result.connection_id,
            current=result.current,
        )

    async def confirm(
        self,
        subject: GoogleManager,
        *,
        attempt_id: str,
        settings: GoogleFinalSettings | GoogleReconnectSettings,
    ) -> GooglePublishedOutput:
        attempt = await self.repository.load(subject, attempt_id)
        registration = (
            None
            if attempt.status is GoogleAttemptStatus.PUBLISHED
            else await self._registration()
        )
        return self._publication(
            await self.repository.confirm(
                subject,
                attempt_id=attempt_id,
                registration=registration,
                settings=settings,
            )
        )

    async def outcome(
        self,
        subject: GoogleManager,
        attempt_id: str,
    ) -> GooglePublishedOutput:
        return self._publication(await self.repository.outcome(subject, attempt_id))

    async def cancel(
        self, subject: GoogleManager, attempt_id: str
    ) -> GoogleCancelOutput:
        outcome = await self.repository.cancel(subject, attempt_id)
        return GoogleCancelOutput(
            cancelled=outcome is None,
            publication=None if outcome is None else self._publication(outcome),
        )

    async def disconnect(self, subject: GoogleManager, toolkit_id: str) -> None:
        await self.repository.disconnect(subject, toolkit_id)

    async def status(
        self,
        subject: GoogleManager,
        toolkit_id: str,
    ) -> GoogleConnectionOutput:
        """Read a saved account without secret material, renewal or resource probes."""
        saved = await self.repository.saved(subject, toolkit_id)
        connection = saved.connection
        status: Literal[
            "not_connected",
            "connected",
            "reconnect_required",
            "operator_setup_required",
            "client_changed",
        ]
        if connection is None:
            status = "not_connected"
        elif connection.status is GoogleConnectionStatus.RECONNECT_REQUIRED:
            status = "reconnect_required"
        else:
            try:
                registration = await self._registration()
            except GoogleOAuthError:
                status = "operator_setup_required"
            else:
                status = (
                    "connected"
                    if registration.client_id == connection.client_id
                    else "client_changed"
                )
        return GoogleConnectionOutput(
            toolkit_id=toolkit_id,
            status=status,
            identity=None if connection is None else connection.candidate.identity,
            selected_tasks=saved.tasks,
            timeout=saved.timeout,
            tasks=self._accesses(
                saved.tasks,
                None
                if connection is None
                else connection.candidate.tokens.granted_scopes,
            ),
            renewable=connection is not None
            and bool(connection.candidate.tokens.refresh_token),
            service_access_verified=False,
        )
