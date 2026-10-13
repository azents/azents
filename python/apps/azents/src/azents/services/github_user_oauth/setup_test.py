"""Setup observation fences, target completeness and explicit provider failures."""

import dataclasses
from typing import NamedTuple
from unittest.mock import AsyncMock, Mock, create_autospec

import pytest

from azents.core.github_installation import GitHubInstallationSnapshot
from azents.core.github_setup import (
    GitHubAppSetupVerification,
    GitHubPATSetupVerification,
    GitHubPlatformSetupVerification,
    GitHubSetupAppIdentity,
    GitHubSetupTransport,
)
from azents.core.github_system_setting_test import _private_key
from azents.core.github_user_auth import GitHubUserProviderError, GitHubUserToken
from azents.core.github_user_creation import GitHubUserCreationSubject
from azents.core.github_user_oauth import GitHubUserErrorCode, GitHubUserOAuthError
from azents.core.tools import TestConnectionResult as ConnectionResult
from azents.repos.github_user_oauth.setup import GitHubSetupRepository
from azents.repos.toolkit_operations.data import PlatformToolkitAuthority
from azents.services.github_user_oauth import setup as github_setup_module
from azents.services.github_user_oauth.service_test import _Harness, _harness
from azents.services.github_user_oauth.setup import GitHubSetupService


def _setup(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    h = _harness(platform=True, agent_id=None)
    h.platform.resolve.return_value = dataclasses.replace(
        h.platform.resolve.return_value, private_key=_private_key()
    )
    h.provider.setup_app.return_value = GitHubSetupAppIdentity(
        app_id="123", name="Actual App", slug="actual-app"
    )
    h.provider.setup_installation_token.return_value = GitHubUserToken(
        "private-probe-token"
    )

    async def installation(
        token: str, *, app_id: str, installation_id: str
    ) -> GitHubInstallationSnapshot:
        assert app_id == "123"
        return GitHubInstallationSnapshot(
            int(installation_id), 123, f"owner-{installation_id}", "Organization", None
        )

    h.provider.setup_installation.side_effect = installation
    monkeypatch.setattr(
        github_setup_module,
        "test_mcp_transport",
        AsyncMock(
            return_value=ConnectionResult(
                success=True,
                message="secret-provider-response",
                discovered_auth_url=None,
                discovered_token_url=None,
                supports_dcr=None,
            )
        ),
    )
    return h


def _subject() -> GitHubUserCreationSubject:
    return GitHubUserCreationSubject("manager", "login", "workspace", None)


class SetupHarness(NamedTuple):
    service: GitHubSetupService
    repository: Mock


def _service_harness(h: _Harness) -> SetupHarness:
    repository = create_autospec(GitHubSetupRepository, instance=True)
    repository.authorize_platform.return_value = None
    return SetupHarness(GitHubSetupService(h.service, repository), repository)


def _service(h: _Harness) -> GitHubSetupService:
    return _service_harness(h).service


def _platform_request() -> GitHubPlatformSetupVerification:
    return GitHubPlatformSetupVerification(
        github_auth_type="github_app_platform",
        installation_ids=["501", "502"],
        transport=GitHubSetupTransport(toolsets=["repos"], timeout=30.0),
    )


async def test_metadata_fresh_lookup_and_exact_pre_post_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _setup(monkeypatch)
    service = _service(h)
    first = await service.app(_subject())
    h.provider.setup_app.return_value = GitHubSetupAppIdentity(
        app_id="123", name="Renamed App", slug="actual-app"
    )
    second = await service.app(_subject())
    assert first.app is not None and first.app.name == "Actual App"
    assert second.app is not None and second.app.name == "Renamed App"
    assert h.provider.setup_app.await_count == 2
    assert h.repository.authorize_scope.await_count == 4
    h.repository.start.assert_not_awaited()


async def test_confirmed_local_absence_does_not_contact_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _setup(monkeypatch)
    h.platform.resolve.return_value = dataclasses.replace(
        h.platform.resolve.return_value,
        app_id=None,
        client_id=None,
        private_key=None,
        client_secret=None,
    )
    output = await _service(h).app(_subject())
    assert output.app is None
    h.provider.setup_app.assert_not_awaited()


async def test_scope_denied_before_any_registration_or_provider_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _setup(monkeypatch)
    h.repository.authorize_scope.side_effect = GitHubUserOAuthError(
        GitHubUserErrorCode.AUTHORITY, "Not a manager."
    )
    with pytest.raises(GitHubUserOAuthError):
        await _service(h).verify(_subject(), _platform_request())
    h.platform.resolve.assert_not_awaited()
    h.provider.setup_app.assert_not_awaited()


@pytest.mark.parametrize("operation", ["app", "verify"])
async def test_scope_loss_after_io_discards_projection(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    h = _setup(monkeypatch)
    h.repository.authorize_scope.side_effect = [
        None,
        GitHubUserOAuthError(GitHubUserErrorCode.AUTHORITY, "No longer a manager."),
    ]
    service = _service(h)
    with pytest.raises(GitHubUserOAuthError):
        if operation == "app":
            await service.app(_subject())
        else:
            await service.verify(_subject(), _platform_request())
    h.provider.setup_app.assert_awaited_once()


@pytest.mark.parametrize("operation", ["app", "verify"])
async def test_changed_platform_registration_after_io_is_stale(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    h = _setup(monkeypatch)
    admitted = h.platform.resolve.return_value
    h.platform.resolve.side_effect = [
        admitted,
        dataclasses.replace(admitted, effective_generation="changed"),
    ]
    service = _service(h)
    with pytest.raises(GitHubUserOAuthError) as caught:
        if operation == "app":
            await service.app(_subject())
        else:
            await service.verify(_subject(), _platform_request())
    assert caught.value.code is GitHubUserErrorCode.STALE


async def test_every_selected_installation_checked_without_trusting_client_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _setup(monkeypatch)
    output = await _service(h).verify(_subject(), _platform_request())
    assert [item.account_login for item in output.installations] == [
        "owner-501",
        "owner-502",
    ]
    assert h.provider.setup_installation.await_count == 2
    assert output.identity.type == "app" and output.identity.name == "Actual App"
    assert output.connectivity.status == "ready"
    assert "secret" not in output.model_dump_json()
    h.repository.start.assert_not_awaited()
    h.repository.confirm.assert_not_awaited()


async def test_target_denial_has_no_fabricated_owner_and_blocks_connectivity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _setup(monkeypatch)
    h.provider.setup_installation.side_effect = [
        GitHubInstallationSnapshot(501, 123, "actual-owner", "User", None),
        GitHubUserProviderError(reason="target_denied", status_code=403),
    ]
    output = await _service(h).verify(_subject(), _platform_request())
    assert output.installations[0].account_login == "actual-owner"
    assert output.installations[1].status == "denied"
    assert output.installations[1].account_login is None
    assert output.installations[1].account_type is None
    assert output.connectivity.status == "failed"
    h.provider.setup_installation_token.assert_not_awaited()
    assert h.provider.setup_installation.await_count == 2


async def test_root_identity_failure_raises_instead_of_fabricating_a_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _setup(monkeypatch)
    h.provider.setup_app.side_effect = GitHubUserProviderError(
        reason="provider_unavailable", status_code=429
    )
    with pytest.raises(GitHubUserProviderError):
        await _service(h).verify(_subject(), _platform_request())
    h.provider.setup_installation.assert_not_awaited()


async def test_unexpected_installation_defect_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _setup(monkeypatch)
    h.provider.setup_installation.side_effect = RuntimeError("implementation defect")
    with pytest.raises(RuntimeError, match="implementation defect"):
        await _service(h).verify(_subject(), _platform_request())


async def test_pat_uses_user_identity_and_sanitized_mcp_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _setup(monkeypatch)
    result = await _service(h).verify(
        _subject(),
        GitHubPATSetupVerification(
            github_auth_type="pat",
            token="private-pat",
            transport=GitHubSetupTransport(toolsets=[], timeout=30.0),
        ),
    )
    h.provider.identity.assert_awaited_once_with("private-pat")
    h.provider.setup_app.assert_not_awaited()
    assert result.identity.type == "user" and result.identity.login == "new-account"
    assert result.installations == []
    assert "private-pat" not in result.model_dump_json()
    assert "secret-provider-response" not in result.model_dump_json()


async def test_self_managed_app_does_not_resolve_platform_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _setup(monkeypatch)
    await _service(h).verify(
        _subject(),
        GitHubAppSetupVerification(
            github_auth_type="github_app",
            app_id="123",
            private_key=_private_key(),
            installation_ids=["501"],
            transport=GitHubSetupTransport(toolsets=[], timeout=30.0),
        ),
    )
    h.platform.resolve.assert_not_awaited()


@pytest.mark.parametrize(
    "field", ["private_key", "client_id", "client_secret", "app_id"]
)
async def test_mode_availability_distinguishes_local_incomplete_registration(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    h = _setup(monkeypatch)
    h.platform.resolve.return_value = dataclasses.replace(
        h.platform.resolve.return_value, **{field: None}
    )
    availability = await h.service.availability(
        user_id="manager", session_id="login", workspace_id="workspace", agent_id=None
    )
    assert availability.platform_modes.user_account == "incomplete"
    assert availability.platform_modes.installation == "incomplete"
    h.provider.setup_app.assert_not_awaited()


async def test_callback_and_local_key_validity_required_for_new_platform_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _setup(monkeypatch)
    result = await h.service.availability(
        user_id="manager", session_id="login", workspace_id="workspace", agent_id=None
    )
    assert result.platform_modes.user_account == "configured"
    assert result.platform_modes.installation == "configured"
    h.platform.resolve.return_value = dataclasses.replace(
        h.platform.resolve.return_value, private_key="invalid-key"
    )
    result = await h.service.availability(
        user_id="manager", session_id="login", workspace_id="workspace", agent_id=None
    )
    assert (
        result.platform == "configured"
    )  # Saved editing preserves its existing field.
    assert result.platform_modes.user_account == "incomplete"
    h.platform.resolve.return_value = dataclasses.replace(
        h.platform.resolve.return_value, private_key=_private_key()
    )
    service = dataclasses.replace(
        h.service, config=h.service.config.model_copy(update={"web_url": None})
    )
    result = await service.availability(
        user_id="manager", session_id="login", workspace_id="workspace", agent_id=None
    )
    assert result.platform_modes.installation == "incomplete"


@pytest.mark.parametrize("reason", ["foreign", "removed"])
async def test_unadmitted_platform_targets_cause_no_provider_or_token_io(
    monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    h = _setup(monkeypatch)
    setup = _service_harness(h)
    setup.repository.authorize_platform.side_effect = GitHubUserOAuthError(
        GitHubUserErrorCode.AUTHORITY, f"Selected installation is {reason}."
    )
    probe = AsyncMock()
    monkeypatch.setattr(github_setup_module, "test_mcp_transport", probe)
    with pytest.raises(GitHubUserOAuthError) as error:
        await setup.service.verify(_subject(), _platform_request())
    assert error.value.code is GitHubUserErrorCode.AUTHORITY
    h.provider.setup_app.assert_not_awaited()
    h.provider.setup_installation.assert_not_awaited()
    h.provider.setup_installation_token.assert_not_awaited()
    h.provider.exchange.assert_not_awaited()
    probe.assert_not_awaited()


async def test_platform_admission_binds_current_user_app_source_and_every_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _setup(monkeypatch)
    setup = _service_harness(h)
    await setup.service.verify(_subject(), _platform_request())
    authority = PlatformToolkitAuthority(
        app_id="123",
        app_id_source=h.platform.resolve.return_value.app_id_source,
        user_id="manager",
        installation_ids=frozenset({501, 502}),
    )
    assert setup.repository.authorize_platform.await_count == 3
    for admission in setup.repository.authorize_platform.await_args_list:
        assert admission.args == (_subject(), authority)


@pytest.mark.parametrize("loss_stage", ["before_token", "after_probe"])
async def test_selected_target_loss_after_io_rejects_projection(
    monkeypatch: pytest.MonkeyPatch, loss_stage: str
) -> None:
    h = _setup(monkeypatch)
    setup = _service_harness(h)
    rejection = GitHubUserOAuthError(
        GitHubUserErrorCode.AUTHORITY, "Selected installation was removed."
    )
    setup.repository.authorize_platform.side_effect = (
        [None, rejection] if loss_stage == "before_token" else [None, None, rejection]
    )
    with pytest.raises(GitHubUserOAuthError) as error:
        await setup.service.verify(_subject(), _platform_request())
    assert error.value.code is GitHubUserErrorCode.AUTHORITY
    h.provider.setup_app.assert_awaited_once()
    assert h.provider.setup_installation.await_count == 2
    if loss_stage == "before_token":
        h.provider.setup_installation_token.assert_not_awaited()
    else:
        h.provider.setup_installation_token.assert_awaited_once()
    h.repository.start.assert_not_awaited()
    h.repository.confirm.assert_not_awaited()


async def test_scope_loss_in_final_combined_target_admission_rejects_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _setup(monkeypatch)
    setup = _service_harness(h)
    setup.repository.authorize_platform.side_effect = [
        None,
        None,
        GitHubUserOAuthError(GitHubUserErrorCode.AUTHORITY, "Agent management lost."),
    ]
    with pytest.raises(GitHubUserOAuthError) as error:
        await setup.service.verify(_subject(), _platform_request())
    assert error.value.code is GitHubUserErrorCode.AUTHORITY
    h.provider.setup_installation_token.assert_awaited_once()


@pytest.mark.parametrize("mode", ["pat", "github_app"])
async def test_personal_credentials_do_not_use_platform_target_authority(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    h = _setup(monkeypatch)
    setup = _service_harness(h)
    transport = GitHubSetupTransport(toolsets=[], timeout=30.0)
    if mode == "pat":
        await setup.service.verify(
            _subject(),
            GitHubPATSetupVerification(
                github_auth_type="pat", token="private-pat", transport=transport
            ),
        )
    else:
        await setup.service.verify(
            _subject(),
            GitHubAppSetupVerification(
                github_auth_type="github_app",
                app_id="123",
                private_key=_private_key(),
                installation_ids=["501"],
                transport=transport,
            ),
        )
    setup.repository.authorize_platform.assert_not_awaited()
