"""Personal Platform acquisition uses exact login and common SDK effects."""

import dataclasses
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
import sqlalchemy as sa

from azents.core.config import Config, CredentialEncryptionConfig
from azents.core.github_installation import GitHubInstallationSnapshot
from azents.core.oauth2 import (
    create_platform_oauth_state,
    verify_personal_platform_oauth_state,
    verify_platform_oauth_state,
)
from azents.core.personal_toolkit import (
    PersonalToolkitAuthorityDenied,
    PersonalToolkitConfigurationConflict,
)
from azents.core.system_setting import SystemSettingFieldSource
from azents.rdb.models.session import RDBSession
from azents.repos.toolkit.personal_management_test import Harness
from azents.repos.toolkit.personal_management_test import (
    fixture as fixture,  # noqa: PLC0414 -- common PostgreSQL fixture
)
from azents.repos.toolkit.personal_management_test import (
    harness as harness,  # noqa: PLC0414 -- current-account DB operations
)
from azents.services.github_platform_system_setting.runtime import (
    ResolvedPlatformGitHubApp,
)
from azents.services.github_user_oauth.personal_installations import (
    PersonalGitHubInstallationsService,
)
from azents.services.toolkit_oauth import service as common
from azents.services.toolkit_oauth.data import ToolkitOAuthError


@dataclasses.dataclass(frozen=True)
class InstallationHarness:
    management: Harness
    service: PersonalGitHubInstallationsService
    platform: ResolvedPlatformGitHubApp
    exchange: AsyncMock
    listing: AsyncMock
    revoke: AsyncMock
    runtime: AsyncMock
    payloads: MagicMock


@pytest.fixture
async def installations(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> InstallationHarness:
    platform = ResolvedPlatformGitHubApp(
        app_id="fixture-app",
        client_id="fixture-client",
        private_key="fixture-private-key",
        client_secret="fixture-client-secret",
        app_id_source=SystemSettingFieldSource.ENVIRONMENT,
        effective_generation="fixture-generation",
    )
    payloads = MagicMock()
    monkeypatch.setattr(harness.repository, "setting_payloads", payloads)
    payloads.resolve_current.return_value = SimpleNamespace(
        effective_generation=platform.effective_generation
    )
    runtime = AsyncMock()
    runtime.resolve.return_value = platform
    exchange = AsyncMock(return_value="fixture-transient-token")
    listing = AsyncMock(
        return_value=[
            GitHubInstallationSnapshot(
                installation_id=42,
                app_id=None,
                account_login="fixture-org",
                account_type="Organization",
                account_avatar_url="https://example.test/avatar",
            )
        ]
    )
    revoke = AsyncMock()
    monkeypatch.setattr(common, "exchange_oauth_code", exchange)
    monkeypatch.setattr(common, "list_user_installations", listing)
    monkeypatch.setattr(common, "revoke_oauth_token", revoke)
    service = PersonalGitHubInstallationsService(
        harness.repository,
        Config.model_construct(
            web_url="https://app.test",
            testenv_api_enabled=False,
            testenv_github_platform_validation_base_url=None,
            credential_encryption=CredentialEncryptionConfig(key="fixture-state-key"),
        ),
        runtime,
    )
    return InstallationHarness(
        harness, service, platform, exchange, listing, revoke, runtime, payloads
    )


async def oauth_state(h: InstallationHarness) -> str:
    return parse_qs(urlsplit(await h.service.oauth_url(h.management.subject)).query)[
        "state"
    ][0]


async def test_personal_platform_sync_uses_existing_user_inventory(
    installations: InstallationHarness,
) -> None:
    h = installations
    assert h.platform.app_id is not None
    state = await oauth_state(h)
    decoded = verify_personal_platform_oauth_state(state, "fixture-state-key")
    assert decoded is not None and decoded.owner.user_id == h.management.subject.user_id
    assert decoded.auth_session_id == h.management.subject.session_id
    assert verify_platform_oauth_state(state, "fixture-state-key") is None
    rows = await h.service.sync(h.management.subject, code="fixture-code", state=state)
    assert len(rows) == 1 and rows[0].id == 42
    h.exchange.assert_awaited_once()
    h.revoke.assert_awaited_once()
    repository = (
        h.management.repository.shared_operations.github_installation_repository
    )
    async with h.management.foundation.writes() as session:
        assert await repository.list_accessible_installation_ids(
            session,
            user_id=h.management.subject.user_id,
            platform_app_id=h.platform.app_id,
            installation_ids=frozenset([42]),
        ) == frozenset([42])
        assert (
            await repository.list_accessible_installation_ids(
                session,
                user_id=h.management.other.user_id,
                platform_app_id=h.platform.app_id,
                installation_ids=frozenset([42]),
            )
            == frozenset()
        )
    # A later authoritative empty provider list prunes this exact User/App inventory.
    h.listing.return_value = []
    await h.service.sync(
        h.management.subject, code="fixture-next-code", state=await oauth_state(h)
    )
    async with h.management.foundation.writes() as session:
        assert (
            await repository.list_accessible_installation_ids(
                session,
                user_id=h.management.subject.user_id,
                platform_app_id=h.platform.app_id,
                installation_ids=frozenset([42]),
            )
            == frozenset()
        )


@pytest.mark.parametrize("wrong", ["user", "session", "shared", "generation"])
async def test_wrong_personal_platform_context_never_exchanges(
    installations: InstallationHarness, wrong: str
) -> None:
    h = installations
    state = await oauth_state(h)
    subject = h.management.subject
    if wrong == "user":
        subject = h.management.other
    elif wrong == "session":
        subject = dataclasses.replace(subject, session_id=h.management.other.session_id)
    elif wrong == "shared":
        state = create_platform_oauth_state(
            "fixture-state-key", effective_generation=h.platform.effective_generation
        )
    else:
        h.runtime.resolve.return_value = dataclasses.replace(
            h.platform, effective_generation="changed"
        )
    with pytest.raises(ToolkitOAuthError):
        await h.service.sync(subject, code="fixture-code", state=state)
    h.exchange.assert_not_awaited()
    h.revoke.assert_not_awaited()


@pytest.mark.parametrize(
    "change", ["revoked_login", "db_generation", "runtime_generation", "db_failure"]
)
async def test_post_exchange_authority_gap_cannot_publish_inventory(
    installations: InstallationHarness, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    h = installations
    state = await oauth_state(h)
    receipt = h.listing.return_value
    assert h.platform.app_id is not None

    async def listing(*args: object, **kwargs: object) -> object:
        del args, kwargs
        if change == "revoked_login":
            async with h.management.foundation.writes() as session:
                await session.write_session.execute(
                    sa.update(RDBSession)
                    .where(RDBSession.id == h.management.subject.session_id)
                    .values(revoked_at=sa.func.now())
                )
        elif change == "db_generation":
            h.payloads.resolve_current.return_value = SimpleNamespace(
                effective_generation="changed"
            )
        elif change == "runtime_generation":
            h.runtime.resolve.return_value = dataclasses.replace(
                h.platform, effective_generation="changed"
            )
        else:

            async def fail(*args: object, **kwargs: object) -> None:
                del args, kwargs
                raise RuntimeError("fixture DB failure")

            monkeypatch.setattr(
                h.management.repository, "sync_platform_installations", fail
            )
        return receipt

    h.listing.side_effect = listing
    error = (
        RuntimeError
        if change == "db_failure"
        else ToolkitOAuthError
        if change == "runtime_generation"
        else PersonalToolkitAuthorityDenied
        if change == "revoked_login"
        else PersonalToolkitConfigurationConflict
    )
    with pytest.raises(error):
        await h.service.sync(h.management.subject, code="fixture-code", state=state)
    h.exchange.assert_awaited_once()
    # Keep the same cleanup sequencing as shared: no revocation after failed sync.
    h.revoke.assert_not_awaited()
    repository = (
        h.management.repository.shared_operations.github_installation_repository
    )
    async with h.management.foundation.writes() as session:
        assert (
            await repository.list_accessible_installation_ids(
                session,
                user_id=h.management.subject.user_id,
                platform_app_id=h.platform.app_id,
                installation_ids=frozenset([42]),
            )
            == frozenset()
        )
