"""Authenticated provider identity account-link OAuth orchestration."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.enums import ExternalChannelProvider
from azents.core.external_account_link import (
    ExternalAccountLinkBusy,
    ExternalAccountLinkConflict,
    ExternalAccountLinkView,
    ExternalAccountOAuthAlreadyConsumed,
    ExternalAccountOAuthAuthSessionMismatch,
    ExternalAccountOAuthConfigurationChanged,
    ExternalAccountOAuthExpired,
    ExternalAccountOAuthInvalidAttempt,
    ExternalAccountOAuthInvalidCallback,
    ExternalAccountOAuthProviderMismatch,
    ExternalAccountOAuthProviderRejected,
    ExternalAccountOAuthProviderUnavailable,
)
from azents.core.external_account_oauth import (
    DiscordIdentityOAuthAdapter,
    ExternalAccountOAuthAdapter,
    ExternalAccountOAuthProviderError,
    SlackIdentityOAuthAdapter,
)
from azents.repos.external_account_link import ExternalAccountLinkRepository
from azents.services.external_account_oauth.service import (
    ExternalAccountOAuthAttemptService,
)
from azents.services.external_account_oauth_system_setting.service import (
    ExternalAccountOAuthSystemSettingService,
)


@dataclass(frozen=True)
class ExternalAccountOAuthStartResult:
    """Authorization URL returned after one durable attempt is created."""

    authorization_url: str


class ExternalAccountOAuthService:
    """Coordinate authenticated OAuth attempts and global link finalization."""

    def __init__(
        self,
        attempts: Annotated[
            ExternalAccountOAuthAttemptService,
            Depends(ExternalAccountOAuthAttemptService),
        ],
        links: Annotated[
            ExternalAccountLinkRepository,
            Depends(ExternalAccountLinkRepository),
        ],
        settings: Annotated[
            ExternalAccountOAuthSystemSettingService,
            Depends(ExternalAccountOAuthSystemSettingService),
        ],
    ) -> None:
        self.attempts = attempts
        self.links = links
        self.settings = settings

    async def start(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        provider: ExternalChannelProvider,
    ) -> ExternalAccountOAuthStartResult:
        """Create one authenticated attempt and return its fixed-provider URL."""
        runtime = await self.settings.resolve_runtime(provider)
        adapter = _adapter(provider)
        use_pkce = provider is ExternalChannelProvider.DISCORD
        created = await self.attempts.create(
            user_id=user_id,
            auth_session_id=auth_session_id,
            provider=provider,
            setting_generation=runtime.setting_generation,
            redirect_uri=runtime.redirect_uri,
            use_pkce=use_pkce,
        )
        return ExternalAccountOAuthStartResult(
            authorization_url=adapter.authorization_url(
                client_id=runtime.client.client_id,
                redirect_uri=runtime.redirect_uri,
                state=created.state,
                code_challenge=created.code_challenge,
            )
        )

    async def exchange(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        provider: ExternalChannelProvider,
        code: str,
        state: str,
    ) -> ExternalAccountLinkView:
        """Claim, exchange, and atomically finalize one provider identity link."""
        if (
            not code
            or len(code) > 2048
            or not code.isascii()
            or not state
            or len(state) > 512
            or not state.isascii()
        ):
            raise ExternalAccountOAuthInvalidAttempt
        callback = await self.settings.resolve_callback_context(provider)
        attempt = await self.attempts.claim(
            state=state,
            user_id=user_id,
            auth_session_id=auth_session_id,
            provider=provider,
            setting_generation=callback.setting_generation,
            redirect_uri=callback.redirect_uri,
        )
        if attempt is None:
            failure_code = await self.attempts.classify_claim_failure(
                state=state,
                user_id=user_id,
                auth_session_id=auth_session_id,
                provider=provider,
                setting_generation=callback.setting_generation,
                redirect_uri=callback.redirect_uri,
            )
            raise _claim_failure(failure_code)
        try:
            runtime = await self.settings.resolve_runtime(provider)
        except ExternalAccountOAuthProviderUnavailable:
            try:
                current_callback = await self.settings.resolve_callback_context(
                    provider
                )
            except ExternalAccountOAuthProviderUnavailable:
                current_callback = None
            if current_callback is not None and (
                current_callback.setting_generation != callback.setting_generation
                or current_callback.redirect_uri != callback.redirect_uri
            ):
                await self.attempts.fail(
                    attempt_id=attempt.id,
                    failure_code="configuration_changed",
                    now=datetime.datetime.now(datetime.UTC),
                )
                raise ExternalAccountOAuthConfigurationChanged from None
            await self.attempts.fail(
                attempt_id=attempt.id,
                failure_code="provider_unavailable",
                now=datetime.datetime.now(datetime.UTC),
            )
            raise
        if (
            runtime.setting_generation != callback.setting_generation
            or runtime.redirect_uri != callback.redirect_uri
        ):
            await self.attempts.fail(
                attempt_id=attempt.id,
                failure_code="configuration_changed",
                now=datetime.datetime.now(datetime.UTC),
            )
            raise ExternalAccountOAuthConfigurationChanged
        adapter = _adapter(provider)
        try:
            identity = await adapter.exchange_identity(
                client_id=runtime.client.client_id,
                client_secret=runtime.client.client_secret,
                code=code,
                redirect_uri=runtime.redirect_uri,
                code_verifier=self.attempts.decrypt_pkce_verifier(attempt),
            )
        except ExternalAccountOAuthProviderError:
            await self.attempts.fail(
                attempt_id=attempt.id,
                failure_code="provider_exchange_failed",
                now=datetime.datetime.now(datetime.UTC),
            )
            raise ExternalAccountOAuthProviderRejected from None
        result = await self.links.finalize_oauth_link(
            attempt_id=attempt.id,
            user_id=user_id,
            auth_session_id=auth_session_id,
            provider=provider,
            setting_generation=runtime.setting_generation,
            redirect_uri=runtime.redirect_uri,
            identity=identity,
            now=datetime.datetime.now(datetime.UTC),
        )
        if result.link is not None:
            return result.link
        if result.failure_code == "configuration_changed":
            raise ExternalAccountOAuthConfigurationChanged
        if result.failure_code == "auth_session_mismatch":
            raise ExternalAccountOAuthAuthSessionMismatch
        if result.failure_code == "busy":
            raise ExternalAccountLinkBusy
        if result.failure_code == "conflict":
            raise ExternalAccountLinkConflict
        if result.failure_code == "malformed_provider_identity":
            raise ExternalAccountOAuthProviderRejected
        raise ExternalAccountOAuthInvalidAttempt


def _claim_failure(failure_code: str) -> Exception:
    """Map one repository-owned claim code to a sanitized domain error."""
    failures: dict[str, type[Exception]] = {
        "expired": ExternalAccountOAuthExpired,
        "already_consumed": ExternalAccountOAuthAlreadyConsumed,
        "auth_session_mismatch": ExternalAccountOAuthAuthSessionMismatch,
        "provider_mismatch": ExternalAccountOAuthProviderMismatch,
        "invalid_callback": ExternalAccountOAuthInvalidCallback,
        "configuration_changed": ExternalAccountOAuthConfigurationChanged,
    }
    failure = failures.get(failure_code, ExternalAccountOAuthInvalidAttempt)
    return failure()


def _adapter(provider: ExternalChannelProvider) -> ExternalAccountOAuthAdapter:
    """Return the fixed adapter for one supported provider."""
    if provider is ExternalChannelProvider.SLACK:
        return SlackIdentityOAuthAdapter()
    return DiscordIdentityOAuthAdapter()
