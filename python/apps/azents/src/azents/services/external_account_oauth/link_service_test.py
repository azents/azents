"""Tests for authenticated provider identity OAuth orchestration."""

import datetime
from typing import Any, cast

import pytest

import azents.services.external_account_oauth.link_service as link_service_module
from azents.core.enums import (
    ExternalAccountOAuthAttemptStatus,
    ExternalChannelProvider,
)
from azents.core.external_account_link import (
    ExternalAccountLinkConflict,
    ExternalAccountLinkState,
    ExternalAccountLinkView,
    ExternalAccountOAuthProviderRejected,
)
from azents.core.external_account_oauth import (
    ExternalAccountOAuthCallbackContext,
    ExternalAccountOAuthClientConfiguration,
    ExternalAccountOAuthIdentity,
    ExternalAccountOAuthProviderError,
    ExternalAccountOAuthRuntimeConfiguration,
)
from azents.repos.external_account_link import ExternalAccountOAuthFinalizeResult
from azents.repos.external_account_oauth.data import ExternalAccountOAuthAttempt
from azents.services.external_account_oauth.link_service import (
    ExternalAccountOAuthService,
)
from azents.services.external_account_oauth.service import (
    ExternalAccountOAuthAttemptStart,
)

_NOW = datetime.datetime(2026, 9, 13, tzinfo=datetime.UTC)


class _FakeSettings:
    """Return one ready provider configuration."""

    async def resolve_callback_context(
        self,
        provider: ExternalChannelProvider,
    ) -> ExternalAccountOAuthCallbackContext:
        return ExternalAccountOAuthCallbackContext(
            setting_generation="generation-1",
            redirect_uri=(
                f"https://azents.example/oauth/external-account/"
                f"{provider.value}/callback"
            ),
        )

    async def resolve_runtime(
        self,
        provider: ExternalChannelProvider,
    ) -> ExternalAccountOAuthRuntimeConfiguration:
        return ExternalAccountOAuthRuntimeConfiguration(
            client=ExternalAccountOAuthClientConfiguration(
                provider=provider,
                client_id=f"{provider.value}-client",
                client_secret="secret",
            ),
            setting_generation="generation-1",
            redirect_uri=(
                f"https://azents.example/oauth/external-account/"
                f"{provider.value}/callback"
            ),
        )


class _FakeAttempts:
    """Capture attempt operations without a database."""

    def __init__(self) -> None:
        self.attempt = ExternalAccountOAuthAttempt(
            id="attempt-1",
            state_hash="hash",
            user_id="user-1",
            auth_session_id="session-1",
            provider=ExternalChannelProvider.DISCORD,
            setting_generation="generation-1",
            redirect_uri="https://azents.example/oauth/external-account/discord/callback",
            encrypted_pkce_verifier="encrypted-verifier",
            status=ExternalAccountOAuthAttemptStatus.CLAIMED,
            expires_at=_NOW + datetime.timedelta(minutes=10),
            claimed_at=_NOW,
            completed_at=None,
            failed_at=None,
            failure_code=None,
            created_at=_NOW,
        )
        self.failed = False

    async def create(self, **_: object) -> ExternalAccountOAuthAttemptStart:
        return ExternalAccountOAuthAttemptStart(
            attempt=self.attempt,
            state="state-value",
            code_verifier="verifier",
            code_challenge="challenge",
        )

    async def claim(self, **_: object) -> ExternalAccountOAuthAttempt:
        return self.attempt

    def decrypt_pkce_verifier(self, _: ExternalAccountOAuthAttempt) -> str:
        return "verifier"

    async def fail(self, **_: object) -> bool:
        self.failed = True
        return True


class _FakeLinks:
    """Return a deterministic global link finalization result."""

    def __init__(self, result: ExternalAccountOAuthFinalizeResult) -> None:
        self.result = result

    async def finalize_oauth_link(
        self,
        **_: object,
    ) -> ExternalAccountOAuthFinalizeResult:
        return self.result


class _FakeAdapter:
    """Deterministic provider adapter used by orchestration tests."""

    def __init__(self, *, failure: bool = False) -> None:
        self.failure = failure

    def authorization_url(self, **kwargs: object) -> str:
        return f"https://provider.example/authorize?state={kwargs['state']}"

    async def exchange_identity(self, **_: object) -> ExternalAccountOAuthIdentity:
        if self.failure:
            raise ExternalAccountOAuthProviderError("provider-body-secret")
        return ExternalAccountOAuthIdentity(
            provider=ExternalChannelProvider.DISCORD,
            identity_scope="global",
            provider_user_id="123456789",
            provider_tenant_id=None,
            provider_tenant_display_label=None,
            provider_display_label="Example User",
        )


def _service(
    attempts: _FakeAttempts,
    links: _FakeLinks,
) -> ExternalAccountOAuthService:
    return ExternalAccountOAuthService(
        attempts=cast(Any, attempts),
        links=cast(Any, links),
        settings=cast(Any, _FakeSettings()),
    )


@pytest.mark.asyncio
async def test_start_creates_authenticated_pkce_attempt_and_provider_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Start returns only the fixed-provider authorization URL."""
    attempts = _FakeAttempts()
    monkeypatch.setattr(
        link_service_module,
        "_adapter",
        lambda _: cast(Any, _FakeAdapter()),
    )
    service = _service(
        attempts,
        _FakeLinks(ExternalAccountOAuthFinalizeResult(None, None)),
    )

    result = await service.start(
        user_id="user-1",
        auth_session_id="session-1",
        provider=ExternalChannelProvider.DISCORD,
    )

    assert result.authorization_url.endswith("state=state-value")


@pytest.mark.asyncio
async def test_exchange_finalizes_global_link_without_retaining_provider_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exchange returns the global link projection after one request-local proof."""
    attempts = _FakeAttempts()
    link = ExternalAccountLinkView(
        id="link-1",
        workspace_id=None,
        workspace_name=None,
        workspace_handle=None,
        user_id="user-1",
        provider=ExternalChannelProvider.DISCORD,
        identity_scope="global",
        provider_user_id="123456789",
        provider_tenant_display_label=None,
        provider_display_label="Example User",
        linked_at=_NOW,
        state=ExternalAccountLinkState.ACTIVE,
    )
    monkeypatch.setattr(
        link_service_module,
        "_adapter",
        lambda _: cast(Any, _FakeAdapter()),
    )
    service = _service(
        attempts,
        _FakeLinks(ExternalAccountOAuthFinalizeResult(link, None)),
    )

    result = await service.exchange(
        user_id="user-1",
        auth_session_id="session-1",
        provider=ExternalChannelProvider.DISCORD,
        code="provider-code",
        state="state-value",
    )

    assert result.id == "link-1"
    assert attempts.failed is False


@pytest.mark.asyncio
async def test_provider_failure_is_sanitized_and_attempt_is_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider response material never crosses the service boundary."""
    attempts = _FakeAttempts()
    monkeypatch.setattr(
        link_service_module,
        "_adapter",
        lambda _: cast(Any, _FakeAdapter(failure=True)),
    )
    service = _service(
        attempts,
        _FakeLinks(ExternalAccountOAuthFinalizeResult(None, None)),
    )

    with pytest.raises(ExternalAccountOAuthProviderRejected):
        await service.exchange(
            user_id="user-1",
            auth_session_id="session-1",
            provider=ExternalChannelProvider.DISCORD,
            code="provider-code",
            state="state-value",
        )
    assert attempts.failed is True


@pytest.mark.asyncio
async def test_global_owner_conflict_is_generic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A link owned by another User is never disclosed by the service."""
    attempts = _FakeAttempts()
    monkeypatch.setattr(
        link_service_module,
        "_adapter",
        lambda _: cast(Any, _FakeAdapter()),
    )
    service = _service(
        attempts,
        _FakeLinks(ExternalAccountOAuthFinalizeResult(None, "conflict")),
    )

    with pytest.raises(ExternalAccountLinkConflict):
        await service.exchange(
            user_id="user-1",
            auth_session_id="session-1",
            provider=ExternalChannelProvider.DISCORD,
            code="provider-code",
            state="state-value",
        )
